# trachhub setup guide

welcome to trachhub! follow these simple steps to download and set up your device.

## requirements

* a raspberry pi with internet access
* a working wifi connection

## step 1: download the setup script

open a terminal on your raspberry pi and run the following command:

```
curl -sSL https://raw.githubusercontent.com/TrachSenseADC/trachhub-scripts/refs/heads/main/setup.sh -o setup.sh
```

## step 2: run the setup script

once downloaded, give the script permission to run:

```
chmod +x setup.sh
```

then start the installation:

```
./setup.sh
```

## what happens next?

* the script will check for an internet connection.
* necessary folders will be created.
* system dependencies like python and git will be installed.
* trachhub files will be downloaded and set up.
* the trachhub server will start automatically.

## troubleshooting

if something goes wrong, check the log file:

```
cat $HOME/TrachHub/setup.log
```

make sure your device is connected to the internet and try running the script again.

## stopping trachhub

trachhub runs in the background. to stop it, simply restart your device.

if you need further assistance, contact support.
