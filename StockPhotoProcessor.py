from __future__ import print_function
import os
import sys
import requests
import json
import re
import argparse
import urllib.error
from bs4 import BeautifulSoup
from tqdm import tqdm
from colored import fg, bg, attr
from google.cloud import vision
import io
from iptcinfo3 import IPTCInfo
from PIL import Image, ImageOps
import sys
from requests.auth import HTTPBasicAuth
import paramiko
import ftplib
import time
from requests_oauthlib import OAuth1Session

if sys.argv[1]:
    CONFIG_FILE_PATH = sys.argv[1]
else:
    print('Missing Arguent: Full path to config.json including filename')
    sys.exit(1)

## Load Config File
config_file = open(CONFIG_FILE_PATH)
config_json = json.load(config_file)
config_file.close

### SMUGMUG INPUTS
SMUGMUG_ACCESS_TOKEN_JSON = config_json['SMUGMUG_ACCESS_TOKEN_JSON']
SMUGMUG_API_KEY = config_json['SMUGMUG_API_KEY']
SMUGMUG_OAUTH_SECRET = config_json['SMUGMUG_OAUTH_SECRET']
SMUGMUG_USER = config_json['SMUGMUG_USER']
SMUGMUG_EXCLUDE_ALBUM_NAMES = config_json['SMUGMUG_EXCLUDE_ALBUM_NAMES']
SMUGMUG_SKIP_ALBUM_COUNT = config_json['SMUGMUG_SKIP_ALBUM_COUNT']

### GOOGLE INPUTS
GOOGLE_VISION_KEY_JSON = config_json['GOOGLE_VISION_KEY_JSON']
TagLimit = config_json['TagLimit']
TitleLimit = config_json['TitleLimit']

## Adobe Stock Inputs
ADOBE_KNOWN_HOSTS_FILE = config_json['ADOBE_KNOWN_HOSTS_FILE']
ADOBE_USER = config_json['ADOBE_USER']
ADOBE_PASSWORD = config_json['ADOBE_PASSWORD']

## ShutterStock Inputs
SHUTTER_USER = config_json['SHUTTER_USER']
SHUTTER_PASSWORD = config_json['SHUTTER_PASSWORD']

### SCRIPT INPUTS
WORKING_PATH = config_json['WORKING_PATH']
endpoint = "https://www.smugmug.com"
LOCAL_IMAGES_TO_PROCESS_PATH = config_json['LOCAL_IMAGES_TO_PROCESS_PATH']

## Counters
KeepAlive = 0
shutterconnect = 0
adobeconnect = 0
skipalbume = 0
processedfiles = 0

## Load SmugMug Access Token
jsontoken = open(SMUGMUG_ACCESS_TOKEN_JSON)
accessToken = json.load(jsontoken)
jsontoken.close

## Set working Paths
if WORKING_PATH[-1:] != "/" and WORKING_PATH[-1:] != "\\":
    output_dir = WORKING_PATH + "/"
else:
    output_dir = WORKING_PATH

if not os.path.exists(output_dir + 'Temp'):
    os.makedirs(output_dir + 'Temp')

if not os.path.exists(output_dir + 'Local'):
    os.makedirs(output_dir + 'Local')

## Parse Album List to Skip
if SMUGMUG_EXCLUDE_ALBUM_NAMES:
    specificAlbums = [x.strip() for x in SMUGMUG_EXCLUDE_ALBUM_NAMES.split('$')]

## Open SmugMug Session
session = OAuth1Session(SMUGMUG_API_KEY,SMUGMUG_OAUTH_SECRET,accessToken["Token"]["id"],accessToken["Token"]["Secret"])

# Gets the JSON output from the SmugMug API call
def get_json(url):
    num_retries = 5
    for i in range(num_retries):
        try:
            r = session.get(endpoint + url)
            soup = BeautifulSoup(r.text, "html.parser")
            pres = soup.find_all("pre")
            return json.loads(pres[-1].text)
        except IndexError:
            print("ERROR: JSON output not found for URL: %s" % url)
            if i+1 < num_retries:
                print("Retrying...")
            else:
                print("ERROR: Retries unsuccessful. Skipping this request.")
            continue
    return None

# Removes all the meta data from a JPEG file
def exif_delete(original_file_path):
    original = Image.open(original_file_path)

    # rotate image to correct orientation before removing EXIF data
    original = ImageOps.exif_transpose(original)

    # create output image, forgetting the EXIF metadata
    stripped = Image.new(original.mode, original.size)
    stripped.putdata(list(original.getdata()))
    stripped.save(original_file_path)

# Retrieve SmugMug the list of albums
print("Downloading album list...", end="")
albums = get_json("/api/v2/folder/user/%s!albumlist" % SMUGMUG_USER)
if albums is None:
    print("ERROR: Could not retrieve album list.")
    sys.exit(1)
print("done.")

# Quit if no albums were found
try:
    albums["Response"]["AlbumList"]
except KeyError:
    sys.exit("No albums were found for the user %s. The user may not exist or may be password protected." % SMUGMUG_USER)

# Create output directories
print("Creating output directories...", end="")
for album in albums["Response"]["AlbumList"]:
    if len(specificAlbums) > 0:
        if album["Name"].strip() in specificAlbums:
            continue

    directory = output_dir + album["UrlPath"][1:]
    if not os.path.exists(directory):
        os.makedirs(directory)
print("done.")

def format_label(s, width=24):
    return s[:width].ljust(width)

bar_format = '{l_bar}{bar:-2}| {n_fmt:>3}/{total_fmt:<3}'

client = vision.ImageAnnotatorClient.from_service_account_json(GOOGLE_VISION_KEY_JSON)

def ProcessFile(file_path):
    global tp
    global sftpClient
    global ftp
    global shutterconnect
    global adobeconnect
    global KeepAlive
    global ADOBE_KNOWN_HOSTS_FILE
    global ADOBE_USER 
    global ADOBE_PASSWORD
    global SHUTTER_USER
    global SHUTTER_PASSWORD
    global TagLimit
    global TitleLimit
    
    ##  Check ShutterStock to make sure still alive
    try:
        if KeepAlive > 1000 and shutterconnect == 1:
            ftp.dir()
            KeepAlive = 0
    except:
        shutterconnect = 0

    #Skip file in cases where it errored and file size is 0
    if os.path.exists(file_path):
        file_stats = os.stat(file_path)
        if file_stats.st_size < 1000:
            os.remove(file_path)
            print('File downloded was zero')
            return(0)
    else:
        return(0)

    ## Load and send file to Google Vision For Logo and Face Detection
    with io.open(file_path, 'rb') as image_file:
        content = image_file.read()

    SourceImage = vision.Image(content=content)

    request = {
    "image": SourceImage,
    "features": [
        {"type_": vision.Feature.Type.FACE_DETECTION},
        {"type_": vision.Feature.Type.LOGO_DETECTION},
        ],
    }

    print('\r\nChecking Face and logo detection')
    try:     
        response = client.annotate_image(request)
    except:
        time.sleep(200)
        response = client.annotate_image(request)

    if response.error.message:
        print('{}\nFor more info on error messages, check: '
            'https://cloud.google.com/apis/design/errors'.format(
                response.error.message))
        print(SourceUri)
        if os.path.isfile(file_path):
            os.remove(file_path)
        return(0)

    FaceLogoCount = 0

    faces = response.face_annotations
    for face in faces:
        FaceLogoCount = FaceLogoCount + 1

    logos = response.logo_annotations
    for logo in logos:
        FaceLogoCount = FaceLogoCount + 1

    if FaceLogoCount > 0:
        print('\r\nImage Contains face or logo. Skipping Image')
        if os.path.isfile(file_path):
            os.remove(file_path)
    else:
        try:
            
            ## Get image metadata if no face or logo was detected
            print('\r\nGathering Image Metadata for image ' + file_path)
            request = {
                "image": SourceImage,
                "features": [
                    {"type_": vision.Feature.Type.LABEL_DETECTION},
                    {"type_": vision.Feature.Type.LANDMARK_DETECTION},
                    {"type_": vision.Feature.Type.OBJECT_LOCALIZATION},
                ],
            }

            try:
                response = client.annotate_image(request)
            except:
                time.sleep(200)
                response = client.annotate_image(request)

            if response.error.message:
                print('{}\nFor more info on error messages, check: '
                    'https://cloud.google.com/apis/design/errors'.format(
                        response.error.message))
                print(SourceUri)
                if os.path.isfile(file_path):
                    os.remove(file_path)
                return(0)

            ## Remove existing image metadata before adding in Google Vision Data
            exif_delete(file_path)
            fileinfo = IPTCInfo(file_path)

            TagCount = 0
            TitleCount = 0

            mytitle = ''

            for landmark in response.landmark_annotations:
                if TagCount < TagLimit:
                    fileinfo['keywords'].append(landmark.description)
                    TagCount = TagCount + 1
                if TitleCount < TitleLimit:
                    if TitleCount == 0:           
                        mytitle = landmark.description
                        TitleCount = TitleCount + 1
                    else:
                        mytitle = mytitle + ' ' + landmark.description
                        TitleCount = TitleCount + 1

            for label in response.label_annotations:
                if TagCount < TagLimit:
                    fileinfo['keywords'].append(label.description)
                    TagCount = TagCount + 1
                if TitleCount < TitleLimit:
                    if TitleCount == 0:           
                        mytitle = label.description
                        TitleCount = TitleCount + 1
                    else:
                        mytitle = mytitle + ' ' + label.description
                        TitleCount = TitleCount + 1

            objects = response.localized_object_annotations

            for object_ in objects:
                if TagCount < TagLimit:
                    fileinfo['keywords'].append(object_.name)
                    TagCount = TagCount + 1
                if TitleCount < TitleLimit:
                    if TitleCount == 0:           
                        mytitle = object_.name
                        TitleCount = TitleCount + 1
                    else:
                        mytitle = mytitle + ' ' + object_.name
                        TitleCount = TitleCount + 1

            mytitle = mytitle.replace(">", "-")
            mytitle = mytitle.replace("<", "-")
            mytitle = mytitle.replace("/", "-")
            mytitle = mytitle.replace("&", "-")

            fileinfo['object name'] = mytitle
            fileinfo['headline'] = mytitle
            fileinfo.save()

            if TagCount == 0 or TitleCount == 0:
                print('\r\nNo Metadata detected - Skipping - ' + SourceUri)
                if os.path.isfile(file_path):
                    os.remove(file_path)
            else:
                if adobeconnect == 0 or shutterconnect == 0:
                    print('Opening Adboe Connection')

                    hostkeys = paramiko.hostkeys.HostKeys (filename=ADOBE_KNOWN_HOSTS_FILE)
                    hostFingerprint = hostkeys.lookup ("sftp.contributor.adobestock.com")['ssh-rsa']    
                    try:
                        tp = paramiko.Transport("sftp.contributor.adobestock.com", 22)
                        tp.set_keepalive(10)
                        tp.connect (username = ADOBE_USER, password=ADOBE_PASSWORD, hostkey=hostFingerprint)
                        try:
                            sftpClient = paramiko.SFTPClient.from_transport(tp)
                            adobeconnect = 1
                        except Exception as err:
                            print ("SFTP failed due to [" + str(err) + "]")
                            adobeconnect = 0
                            return(0)

                    except paramiko.ssh_exception.AuthenticationException as err:
                        print ("Can't connect due to authentication error [" + str(err) + "]")
                        adobeconnect = 0
                    except Exception as err:
                        print ("Can't connect due to other error [" + str(err) + "]")
                        adobeconnect = 0

                    print('Opening Shutterstock Connection')
                    try:
                        ftp = ftplib.FTP_TLS('ftps.shutterstock.com')
                        ftp.trust_server_pasv_ipv4_address = True
                        ftp.login(SHUTTER_USER, SHUTTER_PASSWORD)
                        ftp.prot_p()
                        shutterconnect = 1
                    except:
                        print ('Shutterstock Connection Failed')
                        shutterconnect = 0
                        return(0)


                if adobeconnect == 1 and shutterconnect == 1:    
                    #  Upload to Adobe and Shutterstock
                    print('Uploading to Adobe Stock ' + file_path)
                    try:
                        myresponse = sftpClient.put(file_path, os.path.basename(file_path))
                    except:
                        print('Abobe Upload Failed ' + file_path)
                        adobeconnect = 0
                        if os.path.isfile(image_path):
                            os.remove(image_path)
                        return(0)


                    print('Uploading to Shutterstock ' + file_path)
                    try:
                        ftp.storbinary(f'STOR {os.path.basename(file_path)}',open(file_path,'rb'))
                        KeepAlive = 0
                    except:
                        print('Shutterstock Upload Failed ' + file_path)
                        shutterconnect = 0
                        if os.path.isfile(image_path):
                            os.remove(image_path)
                        return(0)

                try:
                    if os.path.isfile(file_path):
                        os.remove(file_path)
                except:
                    if os.path.isfile(file_path):
                        fp.close()
                        os.remove(file_path)
        except:
            print('\r\nError During tagging and load')
            
            try:
                if os.path.isfile(file_path):
                    os.remove(file_path)
            except:
                if os.path.isfile(file_path):
                    fp.close()
                    os.remove(file_path)

    return(1)


# Loop through each album
for album in tqdm(albums["Response"]["AlbumList"], position=0, leave=True, bar_format=bar_format,
                  desc=f"{fg('yellow')}{attr('bold')}{format_label('All Albums')}{attr('reset')}"):
    
    if skipalbume < SMUGMUG_SKIP_ALBUM_COUNT:
        skipalbume = skipalbume + 1
        print(str(skipalbume)+' - ' + album["Name"].strip())
        continue

    ## Skip Excluded Albums
    if len(specificAlbums) > 0:
        if album["Name"].strip() in specificAlbums:
            continue

    album_path = output_dir + album["UrlPath"][1:]
    images = get_json(album["Uri"] + "!images")
    if images is None:
        print("ERROR: Could not retrieve images for album %s (%s)" %
              (album["Name"], album["Uri"]))
        continue

    # Skip if no images are in the album
    if "AlbumImage" in images["Response"]:

        # Loop through each page of the album
        next_images = images
        while "NextPage" in next_images["Response"]["Pages"]:
            next_images = get_json(
                next_images["Response"]["Pages"]["NextPage"])
            if next_images is None:
                print("ERROR: Could not retrieve images page for album %s (%s)" %
                      (album["Name"], album["Uri"]))
                continue
            images["Response"]["AlbumImage"].extend(
                next_images["Response"]["AlbumImage"])

        # Loop through each image in the album

        for image in tqdm(images["Response"]["AlbumImage"], position=1, leave=True, bar_format=bar_format,
                          desc=f"{attr('bold')}{format_label(album['Name'])}{attr('reset')}"):
            
            filename = re.sub('[^\w\-_\. ]', '_', image["FileName"])
            
            image_path = album_path + "/" + filename

            KeepAlive = KeepAlive + 1

            # Skip if image has already been saved
            if os.path.isfile(image_path):
                #print('Skipping already processed file - ' + image_path)
                continue

            # Skip if file is not an image
            if ".jpg" not in image_path and ".jpeg" not in image_path and ".gif" not in image_path and ".JPG" not in image_path and ".GIF" not in image_path and ".JPEG" not in image_path:
                print('Skipped file that was not am image - ' + image_path)
                with open(image_path, 'w') as fp:
                    pass
                continue

            # Grab video URI if the file is video, otherwise, the standard image URI
            largest_media = "LargestVideo" if "LargestVideo" in image["Uris"] else "LargestImage"
            if largest_media in image["Uris"]:
                image_req = get_json(image["Uris"][largest_media]["Uri"])
                if image_req is None:
                    print("ERROR: Could not retrieve image for %s" %
                          image["Uris"][largest_media]["Uri"])
                    continue
                download_url = image_req["Response"][largest_media]["Url"]
            else:
                # grab archive link if there's no LargestImage URI
                download_url = image["ArchivedUri"]

            #Skip file and dont try again in cases where file is low res small
            SmugMugResolution = 0
            try:
                SmugMugResolution = image_req["Response"][largest_media]["Height"] * image_req["Response"][largest_media]["Width"]
            except:
                continue

            if SmugMugResolution < 3686400 and SmugMugResolution > 0:
                print('File resolution is too small for stock')
                with open(image_path, 'w') as fp:
                    pass
                continue

            try:
                SourceUri = download_url
                
                file_path = output_dir + 'Temp\\' + filename
                r = session.get(SourceUri)   # used to be request.
                with open(file_path, 'wb') as f:
                    for chunk in r.iter_content(chunk_size=128):
                        f.write(chunk)
                f.close()
                
                result = ProcessFile(file_path)
                if result == 1:
                    with open(image_path, 'w') as fp:
                        pass

            except UnicodeEncodeError as ex:
                print("Unicode Error: " + str(ex))
                continue
            except urllib.error.HTTPError as ex:
                print("HTTP Error: " + str(ex))

print("Smugmug Processing Completed.")
print("Starting Local Processing. - " + LOCAL_IMAGES_TO_PROCESS_PATH)

if not os.path.exists(LOCAL_IMAGES_TO_PROCESS_PATH):
    os.makedirs(LOCAL_IMAGES_TO_PROCESS_PATH)

for root, dirs, files in os.walk(LOCAL_IMAGES_TO_PROCESS_PATH):
    for file in files:
        if file.endswith(".jpg") or file.endswith(".jpeg"):

            if os.path.isfile(output_dir +'Local\\' + file):
                os.remove(os.path.join(root, file))
                continue

            result = ProcessFile(os.path.join(root, file))
            if result == 1:
                image_path = output_dir +'Local\\' + file
                with open(image_path, 'w') as fp:
                    pass
