**********    Brought to by https://zombiebunny.org                                        *************
**********    This is a paid script and should not be distributed in full or in part.      *************    
**********    You can modify it for your personal use only                                 *************

This script will:

    Use Google Vision to:
        - Identify images with faces and logos that it will skip loading to stock photo sites
        - Identify metadata that it will add to the photo before uploading the file

    Upload the Images to Adobe Stock and ShutterStock via FTP with the added metadata


To Use:
Create a config.json based on the sample on Github

Refer to SmugMug, ShutterStock, Adobe Stock and Google Vision to gather the required API, OAUTH and Json values to populate the config file
Google Vision:  https://cloud.google.com/vision/docs/setup
SFTP For Adobe Stock: https://www.developer.com/languages/python/python-sftp/
Use the provided example for ShutterStock JSON and Adobe.  You will login to your accoutn to get the required input list API Keys, etc.
