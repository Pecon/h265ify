# h265ify
A tool to automate the process of re-encoding a large collection of videos into newer generation video encoding, for massively reducing filesize at nearly no visible quality loss. All video tracks are re-encoded with libx265, with audio tracks (if applicable) being re-encoded to aac. This script uses the mkv container exclusively, so all outputted files will be .mkv. This script will automatically detect and skip encoding of any files that already have h265 video tracks, and will skip any files that lack video tracks altogether. As much as possible, all video metadata, subtitles, and attachments are preserved.

## Requirements
h265ify requires the `python3` and `ffmpeg` packages. Presently, h265ify only works on unix systems; but it could support Windows with some tweaks. Make an issue if you're interested.

## Usage
Run this script with `python3 h265ify.py [args] directory` or `./h265ify.py [args] directory` or similar. The given directory will be searched recursively for all potentially applicable media files.

h265ify supports the following options:


--help (-h)
+ Displays info about these options, similar to what is documented here.

--suffix (-s) *string*
+ A string to specify what is added to the end of the file name for newly encoded files. If a blank string is given, -x is also required since your source files could be overwritten anyways by way of name conflict. Default is 'h265'.  Example: By default cat.mp4 will re-encode to cath265.mkv

--timeout (-t) *integer*
+ An integer to specify the maximum number of minutes ffmpeg is allowed to spend on a single file. If it takes longer than this, ffmpeg is killed and the file is skipped. Having this set to an amount that makes sense for the content you're encoding is recommended since ffmpeg can get stuck on rare occasions. Set to -1 for no limit. Default: 120

--processes (-p) *integer*
+ An integer to specify how many ffmpeg processes to spawn at once. libx265 has fairly good multithreading by default, so the default of this option is merely 2. Set to 1 to get more breathing room on your CPU while this is running.

--gpu_processes (-g) *integer*
+ An integer to specify how many ffmpeg processes will use hardware-based encoding instead of libx265 CPU encoding. This value is automatically set to 1 if a compatible hardware encoder is detected. Although hardware encoding is incredibly fast, it can produce inferior results compared to CPU encoding. Set this to -1 to completely disable hardware encoding.

--force-nvidia
+ Add this option to force attempting to use nvenc hardware encoding. Use this option if you know your GPU supports nvenc encoding and this script hasn't automatically detected support for it.

--force-amd
+ Same as above but for AMF hardware encoding. 

--overwrite (-o)
+ Add this option to specify that when any file finishes encoding, it should overwrite any existing file it would have a name conflict with. If this option is not specified, name conflicts will result in the conflicting files failing to convert. Default: False

--delete (-x)
+ Add this option switch to specify that you would like source files to be deleted as soon as they are encoded *successfully*. This will not delete source files that fail to encode or are skipped. Default: False

--dry (-d)
+ Add this option switch to specify that you would like newly encoded files to be immediately discarded upon completion. This is useful for checking that your files will encode without immediately committing to the disk space that would be used. Cannot be combined with -x. Default: False

## Why .mkv?
Because mkv has extremely high support for a variety of different types of encoding and metadata, so nearly all media files should be able to encode to mkv without losing anything noteworthy. This is in stark contrast to, say, the .mp4 container format. .mp4 has very strict requirements for what types of metadata it can contain, only supports a single subtitle format, and cannot contain any attachments (which is common in some content for custom subtitle fonts). 
