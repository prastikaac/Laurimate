import sys

# Add the path to your NAOqi SDK
sys.path.append(r"C:\Users\acer\Documents\Programming\Laurimate\pynaoqi\lib")

from naoqi import ALProxy

PEPPER_IP = "192.168.0.118"  
PEPPER_PORT = 9559

tts = ALProxy("ALTextToSpeech", PEPPER_IP, PEPPER_PORT)

tts.say("Hello! Python and NAOqi are working!")