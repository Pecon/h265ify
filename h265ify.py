#!/bin/python3
import sys, time, re, signal;
import subprocess;
from pathlib import Path;
import argparse;

argParser = argparse.ArgumentParser(description = 'Batch convert video files into h265. Depending on your video content, this could save tremendous amounts of disk space.');
argParser.add_argument('-p', '--processes', type = int, help = "Number of ffmpeg processes to spawn while running.", default = 2);
argParser.add_argument('-t', '--timeout', type = int, help = "Maximum minutes to wait for ffmpeg to finish a single file. Leaving this above 0 is recommended since ffmpeg sometimes can get stuck. Use -1 for no time limit. (Default: 120)", default = 120);
argParser.add_argument('-x', '--delete', help = "Delete source files as soon as they are encoded successfully.", action = 'store_true');
argParser.add_argument('-d', '--dry', help = "Discard encoded files as they finish. Use this for testing results.", action = 'store_true');
argParser.add_argument('path', metavar = 'PATH', type = Path, help = "Directory to start discovery of files from.");

args = argParser.parse_args();
print(args);

def error(message):
	print(message, file=sys.stderr);

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
		error("ffprobe returned non-zero exit code for " + str(file));
		return None;

	if probeEncoderSearchExpression.search(info.stderr) != None:
		return None; # Video is already hvec, don't encode

	if probeHasVideoSearchExpression.search(info.stderr) == None:
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

	return subprocess.Popen(command, stdout = subprocess.PIPE, stderr = subprocess.PIPE, stdin = subprocess.PIPE, encoding = 'UTF-8');


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

		print(str(foundFilesCount), end='\r');

if len(foundFiles) <= 0:
	print("No media files found to convert.");
	sys.exit(0);

foundFilesCount = len(foundFiles);
print("Discovered " + str(foundFilesCount) + " media files.");

# Check all the files with ffprobe
i = 0;
for file in foundFiles:
	metadata = checkH265(file);

	if metadata != None:
		validFiles.append(metadata);
	else:
		print("\rSkipping due to already h265: " + file.name);
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
			process['newPath'].unlink();

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
				process['newPath'].unlink();
			else:
				continue;

		elif code == 0:
			# We're good! Time to remove this process and its file
			if args.delete:
				process['originalFile']['path'].unlink();

			if args.dry:
				process['newPath'].unlink();

		else:
			# ffmpeg raised an error... We'll remove the new file since it wasn't finished
			failedFilesCount += 1;

			process['newPath'].unlink();

			print(process['originalFile']['path'].name + " conversion failed, displaying ffmpeg output... Code: ", code);
			print(process['handle'].stdout.read());
			print(process['handle'].stderr.read());

		
		processes.remove(process);
		del process;
		finishedFilesCount += 1;

	# Spawn new processes as needed
	while len(processes) < maxProcesses and len(validFiles) > 0:
		metadata = validFiles.pop();
		filePath = metadata['path'];
		newPath = Path(str(filePath.parent / filePath.stem) + "h265.mkv");

		process = {};
		process['originalFile'] = metadata;
		process['newPath'] = newPath;
		process['handle'] = H265Convert(metadata, newPath);
		process['startTime'] = time.time();
		processes.append(process);

		print("Processing " + str(filePath.name));


	print("Converting: " + str(finishedFilesCount) + "/" + str(validFilesCount) + " " + str(int(finishedFilesCount / validFilesCount * 100)) + "%", end='\r');
	time.sleep(0.1);

print("All files completed. (" + str(failedFilesCount) + " failed)");