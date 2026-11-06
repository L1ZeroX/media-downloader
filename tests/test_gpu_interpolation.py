import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from downloader.core import ROOT
from downloader.gpu_interpolation import frame_plan, interpolate_video
from downloader.worker import convert, encoder_args, probe


class GPUPlanTests(unittest.TestCase):
    def test_rate_and_bounded_batches(self):
        for rate in ("24/1", "30/1", "30000/1001", "50/1"):
            with self.subTest(rate=rate):
                actual, w, h, factor, batch = frame_plan({"avg_frame_rate": rate, "width": 3840, "height": 2160}, "1080p以下")
                self.assertEqual((w, h), (1920, 1080))
                self.assertGreaterEqual(actual * factor, 60)
                self.assertLessEqual(w*h*3*(factor+1)*(batch+1), 512*1024**2)
        self.assertEqual(frame_plan({"avg_frame_rate":"30/1", "width":1920,"height":1080,
                                     "side_data_list":[{"rotation":90}]}, "720p以下")[1:3], (406,720))

    def test_cpu_fallback_reports_reason_and_restarts(self):
        info = {"streams":[{"index":0,"codec_type":"video","codec_name":"h264","pix_fmt":"yuv420p",
                             "avg_frame_rate":"30/1","width":160,"height":96}],"format":{"duration":"2"}}
        result = {"streams":[{**info["streams"][0], "avg_frame_rate":"60/1"}]}
        with tempfile.TemporaryDirectory() as folder:
            target = Path(folder)/"out.mp4"
            def fail(*args):
                target.write_bytes(b"partial")
                raise RuntimeError("GPU unavailable")
            with patch("downloader.worker.probe", side_effect=[info,result]), \
                 patch("downloader.version.IS_BETA", True), \
                 patch("downloader.worker.choose_encoder", return_value="libx264"), \
                 patch("downloader.gpu_interpolation.interpolate_video", side_effect=fail), \
                 patch("downloader.worker.emit") as emit, patch("downloader.worker.run_conversion") as run:
                convert(Path(folder)/"source.mp4", target, {"ffmpeg":"ffmpeg","ffprobe":"ffprobe"}, "MP4","720p以下",60,interpolate=True)
                self.assertFalse(target.exists())
                self.assertIn("minterpolate=", " ".join(run.call_args.args[0]))
                self.assertEqual(run.call_args.args[3], "フレーム補間中（CPU）")
                self.assertTrue(any("GPU unavailable" in str(call) for call in emit.call_args_list))

    def test_gpu_available_in_both_channels_but_cpu_mode_skips_rife(self):
        info = {"streams":[{"index":0,"codec_type":"video","codec_name":"h264","pix_fmt":"yuv420p",
                             "avg_frame_rate":"30/1","width":160,"height":96}],"format":{"duration":"2"}}
        for beta, mode in ((False,"GPU優先"),(True,"GPU優先"),(False,"CPU高速"),(True,"CPU高速")):
            with self.subTest(beta=beta,mode=mode), \
                 patch("downloader.worker.probe", side_effect=[info,{"streams":[{**info["streams"][0],"avg_frame_rate":"60/1"}]}]), \
                 patch("downloader.version.IS_BETA", beta), patch("downloader.worker.choose_encoder",return_value="libx264"), \
                 patch("downloader.gpu_interpolation.interpolate_video") as gpu, \
                 patch("downloader.worker.emit"), patch("downloader.worker.run_conversion"):
                convert(Path("source.mp4"),Path("out.mp4"),{"ffmpeg":"f","ffprobe":"p"},"MP4","720p以下",60,mode,True)
                if mode == "CPU高速":
                    gpu.assert_not_called()
                else:
                    gpu.assert_called_once()


@unittest.skipUnless(os.environ.get("PANDORA_TEST_GPU") == "1", "Opt-in Vulkan GPU integration")
class GPUIntegrationTests(unittest.TestCase):
    def test_real_gpu_frames_audio_duration_and_batch_boundaries(self):
        tools = {name:str(ROOT/"tools"/(name+".exe")) for name in ("ffmpeg","ffprobe")}
        with tempfile.TemporaryDirectory(prefix="GPU 補間 ") as folder:
            folder = Path(folder)
            for rate in ("30", "24000/1001", "30000/1001", "50"):
                with self.subTest(rate=rate):
                    source, output = folder/"元動画.mp4", folder/"出力.mp4"
                    output.unlink(missing_ok=True)
                    subprocess.run([tools["ffmpeg"],"-v","error","-y","-f","lavfi","-i",
                                    f"testsrc2=size=160x96:rate={rate}:duration=1",
                                    *([] if rate == "50" else ["-f","lavfi","-i","sine=duration=1"]),
                                    "-c:v","libx264","-crf","0","-c:a","aac",str(source)],capture_output=True,check=True)
                    metadata = probe(source,tools["ffprobe"])
                    real_plan = frame_plan(metadata["streams"][0],"720p以下")
                    with patch("downloader.gpu_interpolation.frame_plan",return_value=(*real_plan[:4],8)):
                        interpolate_video(source,output,tools,metadata,"720p以下","libx264",
                                          ["-c:v","libx264","-crf","0"],lambda *a,**k:None)
                    result = probe(output,tools["ffprobe"])
                    video = next(s for s in result["streams"] if s["codec_type"] == "video")
                    self.assertEqual(video["avg_frame_rate"],"60/1")
                    self.assertAlmostEqual(float(video["duration"]),float(metadata["streams"][0]["duration"]),delta=1/60+.001)
                    self.assertEqual(any(s["codec_name"] == "aac" for s in result["streams"]), rate != "50")
                    if rate == "30":
                        raw = subprocess.check_output([tools["ffmpeg"],"-v","error","-i",str(output),"-pix_fmt","gray","-f","rawvideo","-"])
                        frames = [raw[i:i+160*96] for i in range(0,len(raw),160*96)]
                        self.assertEqual(len(frames),60)
                        # Ordinary fps=60 duplicates ~30 frames. RIFE creates intermediate images.
                        self.assertLess(sum(a==b for a,b in zip(frames,frames[1:])),4)
                        for boundary in (16,32,48):
                            self.assertNotEqual(frames[boundary-1],frames[boundary])
                    self.assertEqual(list(folder.glob("rife-*")),[])

    @unittest.skipUnless(os.name == "nt", "Windows process tree")
    def test_stop_and_close_kill_active_rife_decoder_and_encoder(self):
        import ctypes
        from ctypes import wintypes
        from downloader.processes import WindowsJob
        kernel = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel.OpenProcess.argtypes = [wintypes.DWORD,wintypes.BOOL,wintypes.DWORD]
        kernel.OpenProcess.restype = wintypes.HANDLE
        kernel.WaitForSingleObject.argtypes = [wintypes.HANDLE,wintypes.DWORD]
        kernel.CloseHandle.argtypes = [wintypes.HANDLE]
        code = '''import json,sys,subprocess
from pathlib import Path
from unittest.mock import patch
from downloader.core import ROOT
from downloader.worker import convert
from downloader import version
version.IS_BETA=True
input()
original=subprocess.Popen
def spawn(*args,**kwargs):
 p=original(*args,**kwargs)
 print(json.dumps({"child":p.pid}),flush=True)
 return p
with patch("subprocess.Popen",spawn):
 convert(Path(sys.argv[1]),Path(sys.argv[2]),{k:str(ROOT/"tools"/(k+".exe")) for k in ("ffmpeg","ffprobe")},"MP4","720p以下",60,"GPU優先",True)
'''
        with tempfile.TemporaryDirectory(prefix="GPU stop ") as folder:
            source = Path(folder)/"source.mp4"
            subprocess.run([str(ROOT/"tools/ffmpeg.exe"),"-v","error","-f","lavfi","-i",
                            "testsrc2=size=1280x720:rate=30:duration=10","-c:v","libx264",str(source)],capture_output=True,check=True)
            for action in ("stop","close"):
                with self.subTest(action=action):
                    parent = subprocess.Popen([sys.executable,"-X","utf8","-u","-c",code,str(source),str(Path(folder)/f"{action}.mp4")],
                                              cwd=ROOT,stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.DEVNULL,
                                              text=True,encoding="utf-8",creationflags=subprocess.CREATE_NO_WINDOW)
                    job, handles = WindowsJob(parent), []
                    try:
                        parent.stdin.write("start\n"); parent.stdin.close()
                        for line in parent.stdout:
                            event = json.loads(line)
                            if "child" in event:
                                handle = kernel.OpenProcess(0x100000,False,event["child"])
                                if handle:
                                    handles.append(handle)
                            if event.get("phase") == "フレーム補間中（GPU / RIFE）":
                                break
                        active = [h for h in handles if kernel.WaitForSingleObject(h,0)==258]
                        self.assertGreaterEqual(len(active),3, "RIFE, decoder and encoder must be running")
                        job.terminate() if action == "stop" else job.close()
                        parent.wait(timeout=10)
                        for handle in active:
                            self.assertEqual(kernel.WaitForSingleObject(handle,5000),0)
                    finally:
                        job.close(); parent.wait(timeout=10); parent.stdout.close()
                        for handle in handles:
                            kernel.CloseHandle(handle)
