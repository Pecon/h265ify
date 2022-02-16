#!/bin/python3
import sys, time, re, signal;
import subprocess;
from pathlib import Path;
import argparse;

defaultTempFileSuffix = 'h265';

def error(message):
	print(message, file=sys.stderr);

argParser = argparse.ArgumentParser(description = 'Batch convert video files into h265. Depending on your video content, this could save tremendous amounts of disk space.');
argParser.add_argument('--suffix', '-s', type = str, help = "Suffix to apply to the names of newly encoded files. Will be placed right before the file extension.", default = defaultTempFileSuffix);
argParser.add_argument('--processes', '-p', type = int, help = "Number of ffmpeg processes to spawn while running.", default = 2);
argParser.add_argument('--timeout', '-t', type = int, help = "Maximum minutes to wait for ffmpeg to finish a single file. Leaving this above 0 is recommended since ffmpeg rarely can get stuck. Use -1 for no time limit. (Default: 120)", default = 120);
argParser.add_argument('--delete', '-x', help = "Delete source files as soon as they are encoded successfully.", action = 'store_true');
argParser.add_argument('--dry', '-d', help = "Discard encoded files as they finish. Use this for testing results.", action = 'store_true');
argParser.add_argument('path', metavar = 'PATH', type = Path, help = "Directory to start discovery of files from.");

args = argParser.parse_args();
print(args);

if args.delete and args.dry:
	error("Refusing to run with both dry and delete options enabled, since this would simply delete all your media files. Choose one or the other.");
	sys.exit(1);

if args.suffix == "" and not args.delete:
	error("Using a blank suffix can result in your source files being overwritten due to name conflicts, so --delete is required for this.");
	sys.exit(1);

if args.delete:
	print("Running in DELETE MODE. Each source file that is successfully re-encoded will be deleted automatically.");
elif args.dry:
	print("Running in DRY-RUN MODE. Each newly encoded file will be deleted upon creation.");

searchDir = args.path.expanduser().resolve();

if searchDir.exists() != True:
	error(str(searchDir) + " path does not exist.");
	sys.exit(1);

if searchDir.is_dir() != True:
	error(str(searchDir) + " is not a directory.");
	sys.exit(1);

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

	metadata = {'path': file};
	metadata['hasAudio'] = probeHasAudioSearchExpression.search(info.stderr) != None;
	return metadata;

def H265Convert(inputMetadata, outputPath):

	inputFile = str(inputMetadata['path']);
	outputFile = str(outputPath);

	command = ['ffmpeg', '-nostdin', '-hide_banner', '-i', inputFile, '-map_metadata', '0', '-c:v', 'libx265', '-c:s', 'copy', '-c:t', 'copy', '-c:d', 'copy'];

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
	if file.suffix in videoFileExtensions:
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
	for process in processes:
		process['handle'].terminate();

		try:
			process['handle'].wait(timeout = 1);
		except Exception as e:
			error("Killing ffmpeg because it is taking too long to terminate");
			process['handle'].kill();
		finally:
			process['tempPath'].unlink();

	sys.exit(130);

signal.signal(signal.SIGINT, exitCleanup);

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
				process['output'] += process['handle'].stdout.read(4096);
				continue;

		elif code == 0:
			# We're good! Time to remove this process and its file
			if args.delete:
				process['originalFile']['path'].unlink();

			if args.dry:
				# Dry run, remove the newly encoded file
				process['tempPath'].unlink();
			elif args.suffix != defaultTempFileSuffix:
				# Move the temporary file name to the name the user requested via --suffix
				process['tempPath'].rename(process['destinationPath']);

		else:
			# ffmpeg raised an error... We'll remove the new file since it wasn't finished
			failedFilesCount += 1;

			process['tempPath'].unlink();
			
			print(process['originalFile']['path'].name + " conversion failed, displaying ffmpeg output... Code: ", code);
			process['output'] += process['handle'].stdout.read();
			print(process['output']);

		
		processes.remove(process);
		del process;
		finishedFilesCount += 1;

	# Spawn new processes as needed
	while len(processes) < maxProcesses and len(validFiles) > 0:
		metadata = validFiles.pop();
		filePath = metadata['path'];
		tempPath = Path(str(filePath.parent / filePath.stem) + defaultTempFileSuffix + ".mkv");
		destinationPath = Path(str(filePath.parent / filePath.stem) + args.suffix + ".mkv");

		if tempPath.exists():
			tempPath.unlink();

		process = {};
		process['originalFile'] = metadata;
		process['tempPath'] = tempPath;
		process['destinationPath'] = destinationPath;
		process['handle'] = H265Convert(metadata, tempPath);
		process['startTime'] = time.time();
		process['output'] = "";
		processes.append(process);

		print("Processing " + str(filePath.name));


	print("Converting: " + str(finishedFilesCount) + "/" + str(validFilesCount) + " " + str(int(finishedFilesCount / validFilesCount * 100)) + "%", end='\r');
	time.sleep(0.1);

print("All files completed. (" + str(failedFilesCount) + " failed)");