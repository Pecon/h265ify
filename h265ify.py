#!/bin/python3
import os, sys, time, re, signal;
import subprocess, argparse;
from shutil import which as Which;
from pathlib import Path;

cpuEncoderOption = ['libx265', '-preset', 'veryslow']; #CPU encoder
nvencEncoderOption = ['hevc_nvenc', '-preset', 'slow']; #NVIDIA gpu encoder
amfEncoderOption = ['hevc_amf']; #AMD gpu encoder

def error(message):
	print(message, file=sys.stderr);

# Ensure we have ffmpeg
if Which('ffmpeg') == None:
	error("No suitable ffmpeg executable was found on your system.");
	sys.exit(1);


# Initialize command line argument parsing
argParser = argparse.ArgumentParser(description = 'Batch convert video files into h265. Depending on your video content, this could save tremendous amounts of disk space.');
argParser.add_argument('--suffix', '-s', type = str, help = "Suffix to apply to the names of newly encoded files. Will be placed right before the file extension.", default = 'h265');
argParser.add_argument('--processes', '-p', type = int, help = "Number of ffmpeg processes to spawn while running.", default = 2);
argParser.add_argument('--gpu_processes', '-g', type = int, help = "Number of ffmpeg processes that will use the GPU. This will be automatically set to 1 if a compatible GPU is detected. Set to a negative number to completely disable GPU encoding.", default = 0);
argParser.add_argument('--force_nvidia', help = "Force enable nvenc support. Use this option if your GPU is not detected but you know it supports nvenc.", action = 'store_true');
argParser.add_argument('--force_amd', help = "Force enable amf support. This is experimental, you can try it if your GPU supports amf hardware encoding.", action = 'store_true');
argParser.add_argument('--timeout', '-t', type = int, help = "Maximum minutes to wait for ffmpeg to finish a single file. Leaving this above 0 is recommended since ffmpeg rarely can get stuck. Use -1 for no time limit. (Default: 120)", default = 120);
argParser.add_argument('--delete', '-x', help = "Delete source files as soon as they are encoded successfully.", action = 'store_true');
argParser.add_argument('--overwrite', '-o', help = "Overwrite existing files when there is a name conflict.", action = 'store_true');
argParser.add_argument('--dry', '-d', help = "Discard encoded files as they finish. Use this for testing results.", action = 'store_true');
argParser.add_argument('--destination', metavar = 'PATH', type = Path, help = "Directory to write output files to. File conflicts will be overwritten without prompting.", default = None);
argParser.add_argument('path', metavar = 'PATH', type = Path, help = "Directory to start discovery of files from.");

args = argParser.parse_args();
print(args);

# Check for bad args
if args.delete and args.dry:
	error("Refusing to run with both dry and delete options enabled, since this would simply delete all your media files. Choose one or the other.");
	sys.exit(1);

if args.suffix == "" and (not args.delete and not args.overwrite):
	error("Using a blank suffix can result in your source files being overwritten due to name conflicts, so --overwrite or --delete is required for this.");
	sys.exit(1);

if args.processes < 1:
	error("--processes cannot be an integer less than 1.");
	sys.exit(1);


# Validate primary search path
searchDir = args.path.expanduser().resolve();

if searchDir.exists() != True:
	error(str(searchDir) + " path does not exist.");
	sys.exit(1);

if searchDir.is_dir() != True:
	error(str(searchDir) + " is not a directory.");
	sys.exit(1);

# Validate destination path, if supplied
destinationDir = searchDir;
if args.destination != None:
	destinationDir = args.destination.expanduser().resolve();

	if destinationDir.exists() != True:
		error(str(destinationDir) + "specified destination path (--destination) does not exist.");
		sys.exit(1);
	elif destinationDir.is_dir() != True:
		error(str(destinationDir) + " specified destination path (--destination) is not a directory.");
		sys.exit(1);

# Warn the user about delete or dry mode
if args.delete:
	print("Running in DELETE MODE. Each source file that is successfully re-encoded will be deleted automatically.");
elif args.dry:
	print("Running in DRY-RUN MODE. Each newly encoded file will be deleted upon creation.");

gpuProcesses = args.gpu_processes;
nvidiaGpuSupport = args.force_nvidia;
amdGpuSupport = args.force_amd;

# Check for nvidia gpu nvenc support
if Which('nvidia-smi') != None:
	supportInfo = subprocess.run(['nvidia-smi', '-L'], capture_output = True, encoding = 'UTF-8');
	if re.search('GeForce (?:(?:GTX|RTX) \d{3,4}(?:\D[^Xx]| X)|.*?Titan \w)', supportInfo.stdout) != None: # Good enough. If you have a quadro you're on your own!
		print("Supported nvenc-accelerated GPU detected.");
		nvidiaGpuSupport = True;

		if args.gpu_processes == 0:
			print("Automatically enabling one GPU process.");
			gpuProcesses += 1;

# Warn about no supported gpus being enabled
if gpuProcesses > 0 and not nvidiaGpuSupport and not amdGpuSupport:
	error("You specified that there should be GPU processes, no supported GPUs were automatically detected. Use --force_nvidia or --force_amd to specify which GPU encoder to try.");


probeEncoderSearchExpression = re.compile('\shevc\s');
probeHasVideoSearchExpression = re.compile('\sVideo:\s');
probeHasAudioSearchExpression = re.compile('\sAudio:\s');
def checkH265(file):
	info = subprocess.run(['ffprobe', '-hide_banner', '-i', str(file)], capture_output = True, encoding = 'UTF-8');

	if info.returncode != 0:
		error(str(file) + ": ffprobe returned non-zero exit code. Skipping.");
		return None;

	if probeEncoderSearchExpression.search(info.stderr) != None:
		error(str(file) + ": Media is already h265. Skipping.");
		return None; # Video is already hvec, don't encode

	if probeHasVideoSearchExpression.search(info.stderr) == None:
		error(str(file) + ": Media has no video track. Skipping.");
		return None; # Media has no video track, don't encode because that would be pointless

	metadata = {'path': file, 'noGPU': False};
	metadata['hasAudio'] = probeHasAudioSearchExpression.search(info.stderr) != None;
	return metadata;

def H265Convert(inputMetadata, outputPath):

	inputFile = str(inputMetadata['path']);
	outputFile = str(outputPath);

	command = ['ffmpeg', '-nostdin', '-hide_banner', '-i', inputFile, '-map_metadata', '0', '-c:v'];

	# Decide what encoder to use
	if inputMetadata['useGPU'] and nvidiaGpuSupport:
		command += nvencEncoderOption;
		print(" (Using nvenc GPU encoding)", end='');
	elif inputMetadata['useGPU'] and amdGpuSupport:
		command += amfEncoderOption;
		print(" (Using amf GPU encoding)", end='');
	else:
		command += cpuEncoderOption;
	

	command += ['-c:s', 'copy', '-c:t', 'copy', '-c:d', 'copy'];

	if inputMetadata['hasAudio']:
		command += ['-c:a', 'aac'];

	command += ['-map', '0', outputFile];

	return subprocess.Popen(command, stdout = subprocess.PIPE, stderr = subprocess.STDOUT, stdin = subprocess.PIPE, encoding = 'UTF-8');


foundFiles = [];
validFiles = [];
foundFilesCount = 0;
validFilesCount = 0;
skippedFilesCount = 0;
failedFilesCount = 0;
finishedFilesCount = 0;

# Recursively find files that match common video extensions
videoFileExtensions = ('.mp4', '.mkv', '.avi', '.mov', '.wmv', '.webm', '.ogv');
for file in Path(searchDir).rglob("*"):
	if file.suffix.lower() in videoFileExtensions:
		foundFiles.append(file);
		foundFilesCount += 1

		print("Discovering: " + str(foundFilesCount) + " files found...", end='\r');

if len(foundFiles) <= 0:
	print("No media files found to convert.");
	sys.exit(0);

foundFilesCount = len(foundFiles);
print("Discovered " + str(foundFilesCount) + " media files.           ");

# Check all the files with ffprobe
i = 0;
for file in foundFiles:
	metadata = checkH265(file);

	if metadata != None:
		validFiles.append(metadata);
	else:
		skippedFilesCount += 1;

	i += 1;
	print("Checking: " + str(i) + "/" + str(foundFilesCount) +  " " + str(int(i / foundFilesCount * 100)) + '%', end='\r');

if len(validFiles) <= 0:
	print("No found files need to be converted to h265.");
	sys.exit(0);

validFilesCount = len(validFiles);
print(str(validFilesCount) + " files are ready to convert. (" + str(skippedFilesCount) + " skipped)");


maxProcesses = args.processes;
processes = [];

# Clean up child processes and unfinished files if we get ctrl+c'd
def exitCleanup(signal, frame):
	error("Got request to terminate, cleaning up...");

	for process in processes:
		process['handle'].terminate();

	for process in processes:
		if process['handle'].poll == None:
			try:
				process['handle'].wait(timeout = 6);
			except Exception as e:
				error("Killing ffmpeg because it is taking too long to terminate");
				process['handle'].kill();

		process['tempPath'].unlink();

	sys.exit(130);

signal.signal(signal.SIGINT, exitCleanup);
signal.signal(signal.SIGHUP, exitCleanup);
signal.signal(signal.SIGTERM, exitCleanup);

while len(validFiles) > 0 or len(processes) > 0:

	# Handle each running process
	for process in processes:
		code = process['handle'].poll();

		if code == None:
			if args.timeout != -1 and process['startTime'] < time.time() - (args.timeout * 60):
				error(process['originalFile']['path'].name + ": Killing ffmpeg process because the timeout limit was reached.");
				process['handle'].kill();
				process['tempPath'].unlink();
			else:
				process['output'] += process['handle'].stdout.read(4096); # Move output out of pipe so it doesn't become full
				continue;

		elif code == 0:
			# FFmpeg exited with OK status, do output checks
			originalSize = process['originalFile']['path'].stat().st_size;
			newSize = process['tempPath'].stat().st_size;

			# If the new file is larger than the original, we don't want to use the new file
			if originalSize <= newSize:
				error(process['originalFile']['path'].name + ": Resulting converted file is larger... ", end='');
				process['tempPath'].unlink();

				if process['originalFile']['useGPU']:
					# We would like to try this again using software encoding instead
					error("Re-queueing the file for software-only encoding.");
					process['originalFile']['noGPU'] = True;
					validFiles.append(process['originalFile']);
				else
					error("Discarding.");

			# New file is smaller, good. Check what needs cleaned up.
			else:
				if args.delete: # User requested original files be deleted
					process['originalFile']['path'].unlink();

				if args.dry: # User requested newly encoded files be discarded
					process['tempPath'].unlink();

				# Move the temporary file to its destination
				process['tempPath'].rename(process['destinationPath']);

		else:
			# ffmpeg raised an error... We'll remove the new file since it wasn't finished
			failedFilesCount += 1;

			process['tempPath'].unlink();
			
			error(process['originalFile']['path'].name + " conversion failed, displaying ffmpeg output...");
			process['output'] += process['handle'].stdout.read();
			error(process['output']);

		if process['originalFile']['useGPU']:
			gpuProcesses += 1;

		processes.remove(process);
		del process;
		finishedFilesCount += 1;

	# Spawn new processes as needed
	while len(processes) < maxProcesses and len(validFiles) > 0:
		metadata = validFiles.pop();
		filePath = metadata['path'];

		# Determine path to this file without the searchDir, lets us copy the directory structure into destinationDir if it was different
		outputDir = destinationDir / filePath.parent.relative_to(searchDir);
		outputDir.mkdir(parents = True, exist_ok=True); # Ensure this path exists in our destination directory

		# Path for the temporary file ffmpeg will write to
		tempPath = Path(str(outputDir / filePath.stem) + args.suffix + ".temp.mkv");
		# Path for finished file to be moved to after successful encoding
		destinationPath = Path(str(outputDir / filePath.stem) + args.suffix + ".mkv");

		if destinationPath.exists() and (not args.overwrite and not args.delete):
			error(str(destinationPath) + ": File exists, skipping encoding. Resolve this with --overwrite or --delete (or try a different --suffix)");
			continue;

		# Decide if this will be a hardware-accelerated thread
		metadata['useGPU'] = False;

		if gpuProcesses > 0 and not metadata['noGPU']:
			gpuProcesses -= 1;
			metadata['useGPU'] = True;

		if tempPath.exists():
			tempPath.unlink();

		print("Processing " + str(filePath.name), end='');

		process = {};
		process['originalFile'] = metadata;
		process['tempPath'] = tempPath;
		process['destinationPath'] = destinationPath;
		process['handle'] = H265Convert(metadata, tempPath);
		process['startTime'] = time.time();
		process['output'] = "";
		processes.append(process);

		print("");


	print("Converting: " + str(finishedFilesCount) + "/" + str(validFilesCount) + " " + str(int(finishedFilesCount / validFilesCount * 100)) + "%", end='\r');
	time.sleep(0.1);

print("All files completed. (" + str(failedFilesCount) + " failed)");