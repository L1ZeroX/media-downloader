import sys

if __name__ == "__main__":
    if "--worker" in sys.argv:
        from downloader.worker import main
        raise SystemExit(main())
    else:
        from downloader.app import main
        main()
