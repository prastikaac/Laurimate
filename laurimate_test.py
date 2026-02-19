import sys

# Add the path to your NAOqi SDK
sys.path.append(r"C:\Users\acer\Downloads\Laurimate\pynaqsdk")

from naoqi import ALProxy

# Replace with your Pepper's IP
PEPPER_IP = "192.168.0.118"  # <-- put your Pepper IP here
PEPPER_PORT = 9559

tts = ALProxy("ALTextToSpeech", PEPPER_IP, PEPPER_PORT)

tts.say("Hello! Python and NAOqi are working!")
