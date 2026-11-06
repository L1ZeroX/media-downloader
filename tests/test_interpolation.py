import json
from pathlib import Path
import subprocess
import tempfile
import unittest
from downloader.interpolation import interpolation_filter
from downloader.worker import conversion_args

ROOT = Path(__file__).resolve().parent.parent


class InterpolationTests(unittest.TestCase):
    def test_low_fps_uses_motion_and_preserves_ending(self):
        value = interpolation_filter(30, 2)
        self.assertIn("mi_mode=mci", value)
        self.assertIn("tpad=stop_mode=clone", value)
        self.assertIn("trim=duration=2.000000", value)
        self.assertIsNone(interpolation_filter(60, 2))
        self.assertIsNone(interpolation_filter(120, 2))
        with self.assertRaises(ValueError): interpolation_filter(None, 2)

    @unittest.skipUnless((ROOT / "tools/ffmpeg.exe").exists(), "Bundled FFmpeg required")
    def test_actual_intermediate_frames_and_output_timing(self):
        ffmpeg, probe = str(ROOT / "tools/ffmpeg.exe"), str(ROOT / "tools/ffprobe.exe")
        def run(args):
            return subprocess.run(args, capture_output=True, check=True, timeout=45).stdout
        with tempfile.TemporaryDirectory() as folder:
            source, target = Path(folder)/"source.mp4", Path(folder)/"out.mp4"
            run([ffmpeg,"-v","error","-f","lavfi","-i","testsrc2=size=160x96:rate=30:duration=2",
                 "-f","lavfi","-i","sine=frequency=440:duration=2","-c:v","libx264","-crf","0","-c:a","aac",str(source)])
            metadata = json.loads(run([probe,"-v","error","-show_streams","-show_format","-of","json",str(source)]))
            args = conversion_args(source,target,metadata,"MP4","720p以下",60,interpolate=True)
            run([ffmpeg,*args])
            result = json.loads(run([probe,"-v","error","-show_streams","-show_format","-of","json",str(target)]))
            video = next(s for s in result["streams"] if s["codec_type"] == "video")
            self.assertEqual(video["avg_frame_rate"],"60/1")
            self.assertAlmostEqual(float(video["duration"]),2,delta=1/60)
            self.assertTrue(any(s["codec_name"] == "aac" for s in result["streams"]))
            def duplicates(filter):
                raw = run([ffmpeg,"-v","error","-i",str(source),"-vf",filter,"-frames:v","20","-f","rawvideo","-pix_fmt","gray","-"])
                size = 160*96
                frames = [raw[i:i+size] for i in range(0,len(raw),size)]
                return sum(a == b for a,b in zip(frames,frames[1:]))
            self.assertGreaterEqual(duplicates("fps=60"),8)
            self.assertLess(duplicates(args[args.index("-vf")+1]),3)
