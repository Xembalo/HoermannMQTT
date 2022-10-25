#!/usr/bin/env python3
from typing import SupportsRound
import re, json
from time import sleep
import RPi.GPIO as GPIO
import paho.mqtt.client as mqtt
import json
import sys
import argparse
import signal

#global Variables
loopEnabled = True
MQTT_CLIENT_IDENTIFIER = ""
MQTT_TOPIC = ""
MQTT_BROKER_ADDRESS = ""
MQTT_PORT = 0
MQTT_USER = ""
MQTT_PASS = ""
MQTT_QOS = 0

#Name GPIO-Pins
GARAGE_UP = 23
GARAGE_DOWN = 24
GARAGE_IMPULSE = 25
GARAGE_CLIMATE = 8

GARAGE_IS_OPENED = 17
GARAGE_IS_CLOSED = 27

FENCE_OPEN = 7
FENCE_CLOSE = 1
FENCE_IMPULSE = 12
FENCE_HALF = 16

FENCE_IS_OPENED = 10
FENCE_IS_CLOSED = 9

INTERVAL = 0.1

def initialize_gpio():
  try: 
    GPIO.setwarnings(False)
    GPIO.setmode(GPIO.BCM)

    GPIO.setup(GARAGE_UP, GPIO.OUT)
    GPIO.setup(GARAGE_DOWN, GPIO.OUT)
    GPIO.setup(GARAGE_IMPULSE, GPIO.OUT)
    GPIO.setup(GARAGE_CLIMATE, GPIO.OUT)
    GPIO.setup(FENCE_OPEN, GPIO.OUT)
    GPIO.setup(FENCE_CLOSE, GPIO.OUT)
    GPIO.setup(FENCE_IMPULSE, GPIO.OUT)
    GPIO.setup(FENCE_HALF, GPIO.OUT)
    
    GPIO.setup(GARAGE_IS_OPENED, GPIO.IN)
    GPIO.setup(GARAGE_IS_CLOSED, GPIO.IN)
    GPIO.setup(FENCE_IS_OPENED, GPIO.IN)
    GPIO.setup(FENCE_IS_CLOSED, GPIO.IN)

    GPIO.output(GARAGE_UP,GPIO.HIGH)
    GPIO.output(GARAGE_DOWN,GPIO.HIGH)
    GPIO.output(GARAGE_IMPULSE,GPIO.HIGH)
    GPIO.output(GARAGE_CLIMATE,GPIO.HIGH)
    GPIO.output(FENCE_OPEN,GPIO.HIGH)
    GPIO.output(FENCE_CLOSE,GPIO.HIGH)
    GPIO.output(FENCE_IMPULSE,GPIO.HIGH)
    GPIO.output(FENCE_HALF,GPIO.HIGH)

    return True
  except:
    return False

def _control(command):
  GPIO.output(command, GPIO.LOW)
  sleep(INTERVAL)
  GPIO.output(command, GPIO.HIGH)

def _read(gate):
  if gate == "garage":
    is_opened = GPIO.input(GARAGE_IS_OPENED)
    is_closed = GPIO.input(GARAGE_IS_CLOSED)
  elif gate == "fence":
    is_opened = GPIO.input(FENCE_IS_OPENED)
    is_closed = GPIO.input(FENCE_IS_CLOSED)
  else:
    is_opened = False
    is_closed = False
  
  return _evaluate_door_position(is_opened, is_closed)

def _evaluate_door_position(is_opened, is_closed):
  if is_opened and not is_closed:
    return 'up'
  elif not is_opened and is_closed:
    return 'down'
  else:
    return 'somewhere'

def move(data):

  #read JSON Content
  try:

    if data['gate'] is None:
      raise ValueError
    else:
      gate = data['gate']

    if data['direction'] is None:
      raise ValueError
    else:
      dir = data['direction']

  except ValueError:
    return

  #validate content
  try:
    if not (gate == "garage" or gate == "fence"):
      raise

    if gate == "garage":
      if dir == "up":
        _control(GARAGE_UP)
      elif dir == "down":
        _control(GARAGE_DOWN)
      elif dir == "impulse":
        _control(GARAGE_IMPULSE)
      elif dir == "climate":
        _control(GARAGE_CLIMATE)
      else:
        raise
    elif gate == "fence":
      if dir == "open":
        _control(FENCE_OPEN)
      elif dir == "close":
        _control(FENCE_CLOSE)
      elif dir == "impulse":
        _control(FENCE_IMPULSE)
      elif dir == "half":
        _control(FENCE_HALF)
      else:
        raise
    else:
      raise

  except:
    return


def get(data):

  #read JSON Content
  try:
    if data is None:
      raise ValueError

    if data['gate'] is None:
      raise ValueError
    else:
      gate = data['gate']

  except ValueError:
    return

  #validate content
  try:
    if not (gate == "garage" or gate == "fence"):
      raise

    if gate == "garage" or gate == "fence":
      position = { 'position': _read(gate) }
      return position

    else:
      raise

  except:
    return

def mqttOnConnect(client, userdata, flags, rc):
    if rc==0:
        client.connected_flag = True
    
def mqttOnDisconnect(client, userdata, rc):
    client.connected_flag = False
    client.loop_stop()

def signal_handler(signal, frame):
    global loopEnabled
    loopEnabled = False


def parseArguments():
    global MQTT_CLIENT_IDENTIFIER
    global MQTT_TOPIC
    global MQTT_BROKER_ADDRESS
    global MQTT_PORT
    global MQTT_USER
    global MQTT_PASS
    global MQTT_QOS


    parser = argparse.ArgumentParser(
            description="MQTT-Client for Hörmann garage door using an Raspberry Pi and Hörmann Universaladapterplatine UAP-1-HCP. Pushes current state and reads commands", 
            epilog="Report bugs, comments or improvements to https://github.com/Xembalo/DoorControlWS",
            usage="%(prog)s [options]")
    
    parser.add_argument("--mqtt_client_identifier", help="MQTT client identifier", metavar='identifier', required=True)
    #parser.add_argument("--mqtt_topic",             help="Topic for stats", metavar='topic')
    parser.add_argument("--mqtt_host",              help="Host or IP of your mqtt broker (e.g. localhost)", metavar='host/ip', required=True)
    parser.add_argument("--mqtt_port",              type=int, default=1883, help="port of your mqtt broker (default: %(default)s)", metavar='port')
    parser.add_argument("--mqtt_user",              help="Username for your mqtt broker", metavar='username')
    parser.add_argument("--mqtt_pass",              help="Password for your mqtt broker", metavar='password')
    
    args = parser.parse_args()

    MQTT_CLIENT_IDENTIFIER      = args.mqtt_client_identifier
    #MQTT_TOPIC                  = args.mqtt_topic
    MQTT_BROKER_ADDRESS         = args.mqtt_host
    MQTT_PORT                   = args.mqtt_port
    MQTT_USER                   = args.mqtt_user
    MQTT_PASS                   = args.mqtt_pass
    
    MQTT_QOS                    = 0

def main():

    parseArguments()

    #initialize gpio ports
    success = initialize_gpio()
    if not success:
        print("GPIO ports cannot initialized")
        sys.exit()

    #Signal Handler for interrupting the loop
    signal.signal(signal.SIGINT, signal_handler)        

    mqtt.Client.connected_flag = False
    mqtt.Client.sent_configuration_flag = False

    client = mqtt.Client(MQTT_CLIENT_IDENTIFIER)
    client.on_connect = mqttOnConnect
    client.on_disconnect = mqttOnDisconnect

    if MQTT_USER != "":
        client.username_pw_set(username=MQTT_USER,password=MQTT_PASS)
    try:
        client.connect(MQTT_BROKER_ADDRESS, MQTT_PORT) 
    except:
        print("MQTT connection failed")
        sys.exit()

    client.will_set(MQTT_TOPIC + "/state","offline",MQTT_QOS,retain=True)

    while loopEnabled:

         #creates mqtt client if nessessary 
        if not client.connected_flag:
            client.loop_start()
            
            try:
                client.connect(MQTT_BROKER_ADDRESS, MQTT_PORT) 
            except:
                #if connection was not successful, try it in next loop again
                print("connection was not successful, try it in next loop again")
                pass

        batteryavg, pv1avg, pv2avg, demandavg, feedingridavg, consumptiongridavg, tempavg, feedinbatteryavg, demandbatteryavg = calcStats(session)

        #push to mqtt and quits connection
        if  client.connected_flag: 
            if not client.sent_configuration_flag:
                pushMqttConfig(client, model, sn, sw_version)
                client.sent_configuration_flag = True

            pushMqttStats(client, now, batteryavg, pv1avg, pv2avg, demandavg, feedingridavg, consumptiongridavg, tempavg, feedinbatteryavg, demandbatteryavg)
        
        time.sleep(30.0 - time.time() % 30.0)

    #send last message
    client.publish(MQTT_TOPIC + "/state", "offline", qos=MQTT_QOS, retain=True)
    client.loop_stop()  
    client.disconnect() 

if __name__ == "__main__":
   main()

