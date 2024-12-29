#!/usr/bin/env python3
import json
import time
import RPi.GPIO as GPIO
import paho.mqtt.client as mqtt
import sys
import signal
from gpiozero import CPUTemperature
from pathlib import Path

import logging
from logging.handlers import TimedRotatingFileHandler

FORMATTER = logging.Formatter("%(asctime)s — %(name)s — %(levelname)s — %(message)s")
LOG_FILE = "my_app.log"

def get_console_handler():
   console_handler = logging.StreamHandler(sys.stdout)
   console_handler.setFormatter(FORMATTER)
   return console_handler

def get_file_handler():
   file_handler = TimedRotatingFileHandler(LOG_FILE, when="s", interval=10, backupCount=5)
   file_handler.setFormatter(FORMATTER)
   return file_handler

def get_logger(logger_name):
   logger = logging.getLogger(logger_name)
   logger.setLevel(logging.DEBUG) # better to have too much log than not enough
   logger.addHandler(get_console_handler())
   logger.addHandler(get_file_handler())
   # with this pattern, it's rarely necessary to propagate the error up to parent
   logger.propagate = False
   return logger

#global Variables
loopEnabled = True
CONFIG = {}
STAT_CACHE = {}

#handle ctrl+c in terminal session
def signal_handler(signal, frame):
    global loopEnabled
    loopEnabled = False

def initialize_gpio():
  try: 
    GPIO.setwarnings(False)
    GPIO.setmode(GPIO.BCM)

    if CONFIG["garage"]["enabled"]:
      GPIO.setup(CONFIG["garage"]["gpio"]["open"], GPIO.OUT)
      GPIO.setup(CONFIG["garage"]["gpio"]["close"], GPIO.OUT)
      GPIO.setup(CONFIG["garage"]["gpio"]["impulse"], GPIO.OUT)
      GPIO.setup(CONFIG["garage"]["gpio"]["climate"], GPIO.OUT)
  
      GPIO.setup(CONFIG["garage"]["gpio"]["is_open"], GPIO.IN, pull_up_down = GPIO.PUD_DOWN)
      GPIO.setup(CONFIG["garage"]["gpio"]["is_closed"], GPIO.IN, pull_up_down = GPIO.PUD_DOWN)
    
      GPIO.output(CONFIG["garage"]["gpio"]["open"],GPIO.HIGH)
      GPIO.output(CONFIG["garage"]["gpio"]["close"],GPIO.HIGH)
      GPIO.output(CONFIG["garage"]["gpio"]["impulse"],GPIO.HIGH)
      GPIO.output(CONFIG["garage"]["gpio"]["climate"],GPIO.HIGH)
    
    if CONFIG["fence"]["enabled"]:

      GPIO.setup(CONFIG["fence"]["gpio"]["open"], GPIO.OUT)
      GPIO.setup(CONFIG["fence"]["gpio"]["close"], GPIO.OUT)
      GPIO.setup(CONFIG["fence"]["gpio"]["impulse"], GPIO.OUT)
      GPIO.setup(CONFIG["fence"]["gpio"]["half"], GPIO.OUT)
      
      GPIO.setup(CONFIG["fence"]["gpio"]["is_open"], GPIO.IN, pull_up_down = GPIO.PUD_DOWN)
      GPIO.setup(CONFIG["fence"]["gpio"]["is_closed"], GPIO.IN, pull_up_down = GPIO.PUD_DOWN)

      GPIO.output(CONFIG["fence"]["gpio"]["open"],GPIO.HIGH)
      GPIO.output(CONFIG["fence"]["gpio"]["close"],GPIO.HIGH)
      GPIO.output(CONFIG["fence"]["gpio"]["impulse"],GPIO.HIGH)
      GPIO.output(CONFIG["fence"]["gpio"]["half"],GPIO.HIGH)

    return True
  except:
    return False

def initialize_cache() -> None:
    global STAT_CACHE
    STAT_CACHE = {}
    STAT_CACHE["cputemp"] = 0
    STAT_CACHE["garage"] = {}
    STAT_CACHE["garage"]["state"] = ""
    STAT_CACHE["garage"]["position"] = ""
    STAT_CACHE["garage"]["light"] = ""
    STAT_CACHE["garage"]["venting"] = ""
    STAT_CACHE["garage"]["command"] = ""
    STAT_CACHE["garage"]["last_command_time"] = 0

    print(STAT_CACHE)

def read_config() -> bool:
    global CONFIG

    filename = Path(__file__).with_suffix(".config")
    print(filename)

    #try reading file
    try:
        with open(filename) as infile:
            CONFIG = json.load(infile)
            return True
    except EnvironmentError:
        CONFIG = {}
        return False

def toggle(pin: int):
  GPIO.output(pin, GPIO.LOW)
  time.sleep(0.1)
  GPIO.output(pin, GPIO.HIGH)

def get(pin: int) -> bool:
    return GPIO.input(pin)

def moveDoor(door: str, command: str):
    global STAT_CACHE

    pin = -1

    # assign GPIO pin
    if command == "OPEN":
        pin = CONFIG["garage"]["gpio"]["open"] if door == "garage" else CONFIG["fence"]["gpio"]["open"]
    elif command == "CLOSE":
        pin = CONFIG["garage"]["gpio"]["close"] if door == "garage" else CONFIG["fence"]["gpio"]["close"]
    elif command == "STOP" and STAT_CACHE[door]["command"] in ["OPEN", "CLOSE"]:
        pin = CONFIG["garage"]["gpio"]["impulse"] if door == "garage" else CONFIG["fence"]["gpio"]["impulse"]
    elif command == "VENTING":
        pin = CONFIG["garage"]["gpio"]["climate"]
    elif command == "HALF":
        pin = CONFIG["fence"]["gpio"]["half"]

    if pin > -1: toggle(pin)
    STAT_CACHE[door]["command"] = command if command != "STOP" else ""
    STAT_CACHE[door]["last_command_time"] = time.perf_counter() if command != "STOP" else 0

def printStat(stats: tuple) -> None:
    print("State: " + stats["state"] + ", Position: " + str(stats["position"]) + ", Command: " + stats["command"] + ", Sec after last command: " + str(round(stats["last_command_time"], 1)))
    #my_logger = get_logger("printStat")
   # my_logger.debug("State: " + stats["state"] + ", Position: " + str(stats["position"]) + ", Command: " + stats["command"] + ", Sec after last command: " + str(round(stats["last_command_time"], 1)))

def calculateDoorPosition(door: str) -> tuple[str, int]:
    global STAT_CACHE

    # assign GPIO pins
    pin_is_open = CONFIG["garage"]["gpio"]["is_open"] if door == "garage" else CONFIG["fence"]["gpio"]["is_open"]
    pin_is_closed = CONFIG["garage"]["gpio"]["is_closed"] if door == "garage" else CONFIG["fence"]["gpio"]["is_closed"]

    is_opened = get(pin_is_open)
    is_closed = get(pin_is_closed)

    now = time.perf_counter()

    # default return values
    state = "OPEN"
    position = 50

    printStat(STAT_CACHE[door])

    if is_opened and not is_closed:
        
        state = "OPEN"
        position = 100

        print("door is open")

        if STAT_CACHE[door]["command"] != "" and now - (STAT_CACHE[door]["last_command_time"] or now) > 2:
            # last command is older as 2 seconds, reset
            
            print("Reset open command")
            STAT_CACHE[door]["command"] = ""
            STAT_CACHE[door]["last_command_time"] = 0
        
    elif not is_opened and is_closed:
        state = "CLOSED"
        position = 0

        print("door is closed")

        #STAT_CACHE[door]["state"] = state
        #STAT_CACHE[door]["position"] = position
        if STAT_CACHE[door]["command"] != "" and now - (STAT_CACHE[door]["last_command_time"] or now) > 2:
            # last command is older as 2 seconds, reset

            print("Reset close command")
            STAT_CACHE[door]["command"] = ""
            STAT_CACHE[door]["last_command_time"] = 0

    else:
        # undefined state
        print ("undefined state")

        # try to interprete command from remote control
        if not STAT_CACHE[door]["command"]:
            if STAT_CACHE[door]["state"] == "OPEN" and STAT_CACHE[door]["position"] == 100:
                # The last known state is completely open, but the open-state-sensor is not active, so the command must be "close".
                STAT_CACHE[door]["command"] = "CLOSE"
            elif STAT_CACHE[door]["state"] == "CLOSED" and STAT_CACHE[door]["position"] == 0:
                # The last known state is completely closed, but the closed-state-sensor is not active, so the command must be "open".
                STAT_CACHE[door]["command"] = "OPEN"
        
        if STAT_CACHE[door]["state"] in ["VENTING", "HALF"]:
            print("Venting still active")
            printStat(STAT_CACHE[door])

            # venting/half open?
            state = STAT_CACHE[door]["state"]
            position = STAT_CACHE[door]["position"]
        elif STAT_CACHE[door]["command"] in ["VENTING", "HALF"]:
            # act. command is venting/half open
            
            print("Venting-Command")
            printStat(STAT_CACHE[door])
            
            state = STAT_CACHE[door]["command"]
            position = 10
            STAT_CACHE[door]["command"] = ""
            STAT_CACHE[door]["last_command_time"] = 0

            print("State is now:")
            printStat(STAT_CACHE[door])

        elif STAT_CACHE[door]["command"] in ["OPEN", "CLOSE"]:
            # act. command is open/close

            print("Command " + STAT_CACHE[door]["command"] + " found")
            printStat(STAT_CACHE[door])

            if STAT_CACHE[door]["last_command_time"] == 0:
                # command is new, start measurement
                STAT_CACHE[door]["last_command_time"] = now
                print("Save time")
            
            if STAT_CACHE[door]["state"] in ["OPEN", "CLOSING"] and STAT_CACHE[door]["command"] == "CLOSE":
                # door is closing
                max_movement_time = STAT_CACHE["garage"]["close_time"]
                if now - STAT_CACHE[door]["last_command_time"] > max_movement_time + 1: # +1 additional second
                    # movement last to long, door is stopped, e.g. by remote control or malfunction or because something is in the path of movement
                    state = "OPEN"
                    position = 50 # somewhere, lets say at 50%
                    STAT_CACHE[door]["command"] = ""
                    STAT_CACHE[door]["last_command_time"] = 0
                else:
                    # on the way, calculate position
                    state = "CLOSING"
                    position = round(max(100 - (now - STAT_CACHE[door]["last_command_time"]) * 100 / max_movement_time, 0))

            elif STAT_CACHE[door]["state"] in ["CLOSED", "OPENING"] and STAT_CACHE[door]["command"] == "OPEN":

                print("Door is opening")
                printStat(STAT_CACHE[door])

                # door is opening
                max_movement_time = STAT_CACHE["garage"]["open_time"]
                if now - STAT_CACHE[door]["last_command_time"] > max_movement_time + 1: # +1 additional second
                    # movement last to long, door is stopped, e.g. by remote control or malfunction or because something is in the path of movement
                    state = "OPEN"
                    position = 50 # somewhere, lets say at 50%
                    STAT_CACHE[door]["command"] = ""
                    STAT_CACHE[door]["last_command_time"] = 0
                else:
                    # on the way, calculate position
                    state = "OPENING"
                    position = round(min((now - STAT_CACHE[door]["last_command_time"]) * 100 / max_movement_time, 100))

    return state, position

def switchLight(on: bool):
    #TODO
    #Check Light state and toggle
    pass

def getLight():
    return "OFF" #TODO 

def evaluateCommand(topic: str, command: str):
    if topic == CONFIG["garage"]["mqtt"]["topic"] + "/command" and CONFIG["garage"]["enabled"]: 
        if command in ["OPEN", "CLOSE", "STOP", "VENTING"]:
            moveDoor("garage", command)
        elif command == "LIGHT_OFF":
            switchLight(False)
        elif command == "LIGHT_ON":
            switchLight(True)
        #else: do nothing
    elif topic == CONFIG["fence"]["mqtt_topic"] + "/command" and CONFIG["fence"]["enabled"]:
        if command in ["OPEN", "CLOSE", "STOP", "HALF"]:
            moveDoor("fence", command)
        #else: do nothing    
    #else: do nothing
    pass

def mqttBuildTopic(type: str, device_id: str, name_suffix: str) -> str:
    return "homeassistant/" + type + "/" + device_id + "/" + device_id + "_" + name_suffix + "/config"

def mqttPushConfig(mqttclient):
  #push auto discovery info for home assistant
  #   
  if mqttclient.connected_flag and not mqttclient.sent_configuration_flag:

    if CONFIG["garage"]["enabled"]:

        #Device Identifiers
        device = {}
        device["manufacturer"] = CONFIG["garage"]["mqtt"]["manufacturer"]
        device["model"] = CONFIG["garage"]["mqtt"]["model"]
        device["name"] = CONFIG["garage"]["mqtt"]["name"]
        device["identifiers"] = CONFIG["garage"]["mqtt"]["identifiers"]
        device["hw_version"] = CONFIG["garage"]["mqtt"]["hw_version"]

        #Cover config
        data = {}
        data["availability_topic"] = CONFIG["garage"]["mqtt"]["topic"] + "/availability"
        data["command_topic"] = CONFIG["garage"]["mqtt"]["topic"] + "/command"
        data["device"] = device
        data["device_class"] = "garage"
        data["icon"] = "mdi:garage-variant"
        data["name"] = "Garagentor"
        data["object_id"] = CONFIG["garage"]["mqtt"]["topic"] + "_cover"
        data["state_topic"] = CONFIG["garage"]["mqtt"]["topic"] + "/state"
        data["position_topic"] = CONFIG["garage"]["mqtt"]["topic"] + "/position"
        data["unique_id"] = CONFIG["garage"]["mqtt"]["topic"] + "_cover"
        data["state_open"] = "OPEN"
        data["state_opening"] = "OPENING"
        data["state_closed"] = "CLOSED"
        data["state_closing"] = "CLOSING"
        data["state_stopped"] = "STOPPED"
        data["payload_available"] = "online"
        data["payload_not_available"] = "offline"
        data["payload_open"] = "OPEN"
        data["payload_close"] = "CLOSE"
        data["payload_stop"] = "STOP"
        # set_position_topic 
        mqttclient.publish(mqttBuildTopic("cover", CONFIG["garage"]["mqtt"]["topic"], "cover"), json.dumps(data), qos=CONFIG["mqtt"]["qos"], retain=True)
        
        #Venting Switch
        data = {}
        data["availability_topic"] = CONFIG["garage"]["mqtt"]["topic"] + "/availability"
        data["command_topic"] = CONFIG["garage"]["mqtt"]["topic"] + "/command"
        data["device"] = device
        data["icon"] = "mdi:hvac"
        data["name"] = "Lüften"
        data["object_id"] = CONFIG["garage"]["mqtt"]["topic"] + "_venting"
        data["state_topic"] = CONFIG["garage"]["mqtt"]["topic"] + "/venting"
        data["unique_id"] = CONFIG["garage"]["mqtt"]["topic"] + "_venting"
        data["payload_available"] = "online"
        data["payload_not_available"] = "offline"
        data["payload_off"] = "CLOSE"
        data["payload_on"] = "VENTING"
        data["state_off"] = "OFF"
        data["state_on"] = "ON"
        mqttclient.publish(mqttBuildTopic("switch", CONFIG["garage"]["mqtt"]["topic"], "venting"), json.dumps(data), qos=CONFIG["mqtt"]["qos"], retain=True)

        #Light Switch (overide some values and republish)
        data["icon"] = "mdi:lightbulb"
        data["name"] = "Licht"
        data["object_id"] = CONFIG["garage"]["mqtt"]["topic"] + "_light"
        data["state_topic"] = CONFIG["garage"]["mqtt"]["topic"] + "/light"
        data["unique_id"] = CONFIG["garage"]["mqtt"]["topic"] + "_light"
        data["payload_off"] = "LIGHT_OFF"
        data["payload_on"] = "LIGHT_ON"
        mqttclient.publish(mqttBuildTopic("switch", CONFIG["garage"]["mqtt"]["topic"], "light"), json.dumps(data), qos=CONFIG["mqtt"]["qos"], retain=True)

        #CPU-Temperature
        data = {}
        data["availability_topic"] = CONFIG["garage"]["mqtt"]["topic"] + "/availability"
        data["device"] = device
        data["device_class"] = "temperature"
        data["name"] = "CPU-Temperatur"
        data["object_id"] = CONFIG["garage"]["mqtt"]["topic"] + "_cputemperature"
        data["state_class"] = "measurement"
        data["state_topic"] = CONFIG["garage"]["mqtt"]["topic"] + "/cputemperature"
        data["unique_id"] = CONFIG["garage"]["mqtt"]["topic"] + "_cputemperature"
        data["unit_of_measurement"] = "°C"
        mqttclient.publish(mqttBuildTopic("sensor", CONFIG["garage"]["mqtt"]["topic"], "cputemperature"), json.dumps(data), qos=CONFIG["mqtt"]["qos"], retain=True)

    mqttclient.sent_configuration_flag = True

def mqttOnConnect(mqttclient, userdata, flags, rc):
    if rc==0:
        mqttclient.connected_flag = True
        if CONFIG["garage"]["enabled"]:
            mqttclient.publish(CONFIG["garage"]["mqtt"]["topic"] + "/availability", "online", qos=CONFIG["mqtt"]["qos"], retain=True)
            mqttclient.subscribe(CONFIG["garage"]["mqtt"]["topic"] + "/command", 0)
        if CONFIG["fence"]["enabled"]:
            mqttclient.publish(CONFIG["fence"]["mqtt_topic"] + "/availability", "online", qos=CONFIG["mqtt"]["qos"], retain=True)
            mqttclient.subscribe(CONFIG["fence"]["mqtt_topic"] + "/command", 0)            

def mqttOnDisconnect(mqttclient, userdata, rc):
    mqttclient.connected_flag = False

def mqttOnMessage(mqttclient, userdata, message):
    print("message received",str(message.payload.decode("utf-8")),"topic",message.topic)
    evaluateCommand(message.topic, str(message.payload.decode("utf-8")))

def mqttGetAndPushCPUTemp(mqttclient):
  global STAT_CACHE

  cpu = CPUTemperature()
  cputemp = round(cpu.temperature,1)

  if cputemp != STAT_CACHE["cputemp"]:
    mqttclient.publish(CONFIG["garage"]["mqtt"]["topic"] + "/cputemperature", cputemp, qos=CONFIG["mqtt"]["qos"])
    STAT_CACHE["cputemp"] = cputemp

def mqttGetAndPushDoorState(mqttclient):
    global STAT_CACHE

    #use rentain-flags, otherwise home assitant will not know the state 
    #until every state was changed by door movement

    if CONFIG["garage"]["enabled"]:
        state, position = calculateDoorPosition("garage")
        if state == "VENTING":
            venting = "ON" 
        else:
            venting = "OFF"
        
        if venting != STAT_CACHE["garage"]["venting"]:
            mqttclient.publish(CONFIG["garage"]["mqtt"]["topic"] + "/venting", venting, qos=CONFIG["mqtt"]["qos"], retain=True)
            STAT_CACHE["garage"]["venting"] = venting

        if state != STAT_CACHE["garage"]["state"]:
            if state == "VENTING":
                mqttclient.publish(CONFIG["garage"]["mqtt"]["topic"] + "/state", "OPEN", qos=CONFIG["mqtt"]["qos"], retain=True)
            else:
                mqttclient.publish(CONFIG["garage"]["mqtt"]["topic"] + "/state", state, qos=CONFIG["mqtt"]["qos"], retain=True)
            STAT_CACHE["garage"]["state"] = state
        
        if position != STAT_CACHE["garage"]["position"]:
            mqttclient.publish(CONFIG["garage"]["mqtt"]["topic"] + "/position", position, qos=CONFIG["mqtt"]["qos"], retain=True)
            STAT_CACHE["garage"]["position"] = position
        
        #Read the Light
        light = getLight()
        if light != STAT_CACHE["garage"]["light"]:
          mqttclient.publish(CONFIG["garage"]["mqtt"]["topic"] + "/light", light, qos=CONFIG["mqtt"]["qos"], retain=True)
          STAT_CACHE["garage"]["light"] = light

    if CONFIG["fence"]["enabled"]:
        state, position = calculateDoorPosition("fence")
        if state == "HALF":
            venting = "ON" 
            state = "OPEN"
        else:
            venting = "OFF"
        
        if venting != STAT_CACHE["fence"]["half"]:
            mqttclient.publish(CONFIG["fence"]["mqtt_topic"] + "/half", venting, qos=CONFIG["mqtt"]["qos"], retain=True)
            STAT_CACHE["fence"]["half"] = venting

        if state != STAT_CACHE["fence"]["state"]:
            mqttclient.publish(CONFIG["fence"]["mqtt_topic"] + "/state", state, qos=CONFIG["mqtt"]["qos"], retain=True)
            STAT_CACHE["fence"]["state"] = state
        
        if position != STAT_CACHE["fence"]["position"]:
            mqttclient.publish(CONFIG["fence"]["mqtt_topic"] + "/position", position, qos=CONFIG["mqtt"]["qos"], retain=True)
            STAT_CACHE["fence"]["position"] = position


def mqttInitialize():
    mqtt.Client.connected_flag = False
    mqtt.Client.sent_configuration_flag = False

    client = mqtt.Client(CONFIG["mqtt"]["client_identifier"])
    client.on_connect = mqttOnConnect
    client.on_disconnect = mqttOnDisconnect
    client.on_message = mqttOnMessage

    if CONFIG["mqtt"]["user"] != "":
        client.username_pw_set(username=CONFIG["mqtt"]["user"],password=CONFIG["mqtt"]["password"])

    try:
        client.connect(CONFIG["mqtt"]["broker_address"], CONFIG["mqtt"]["port"]) 
    except:
        print("MQTT connection failed")
        sys.exit()

    #Last-Will-Messages
    if CONFIG["garage"]["enabled"]:
        client.will_set(CONFIG["garage"]["mqtt"]["topic"] + "/availability","offline",CONFIG["mqtt"]["qos"],retain=True)
    
    if CONFIG["fence"]["enabled"]:
        client.will_set(CONFIG["fence"]["mqtt_topic"] + "/availability","offline",CONFIG["mqtt"]["qos"],retain=True)

    return client

def mqttConnect(mqttclient) -> bool:
  success = True
  #creates mqtt client if nessessary 
  if not mqttclient.connected_flag:
      mqttclient.loop_start()
      try:
          mqttclient.connect(CONFIG["mqtt"]["broker_address"], CONFIG["mqtt"]["port"])
      except:
          #if connection was not successful, try it in next loop again
          print("connection was not successful, try it in next loop again")
          success = False

  return success

def mqttDisconnect(mqttclient):
    mqttclient.publish(CONFIG["garage"]["mqtt"]["topic"] + "/availability", "offline", qos=CONFIG["mqtt"]["qos"], retain=True)
    mqttclient.loop_stop()
    mqttclient.disconnect()

def getMovingTimes():
    # determine time span for door movement
    # read from file, and if file does not exists, measure

    global STAT_CACHE

    def measureMovingTime(door: str) -> tuple[float, float]:
        # measure moving time of garage or fence door
        
        def measure(command_pin: int, check_pin: int) -> float:
            # move door and wait for new state

            start_time = time.perf_counter()
            toggle(command_pin)

            while not get(check_pin):
                time.sleep(0.1)

            return round(time.perf_counter() - start_time, 1)
                
        if door not in ["garage", "fence"]:
            return 0.0, 0.0

        # assign GPIO pins
        is_garage = door == "garage"

        pin_open = CONFIG["garage"]["gpio"]["open"] if is_garage else CONFIG["fence"]["gpio"]["open"]
        pin_close = CONFIG["garage"]["gpio"]["close"] if is_garage else CONFIG["fence"]["gpio"]["open"]
        pin_check_open = CONFIG["garage"]["gpio"]["is_open"] if is_garage else CONFIG["fence"]["gpio"]["is_open"]
        pin_check_closed = CONFIG["garage"]["gpio"]["is_closed"] if is_garage else CONFIG["fence"]["gpio"]["is_closed"]

        # check door position
        is_opened = get(pin_check_open)
        is_closed = get(pin_check_closed)
        if is_closed and not is_opened:
            # door is closed, measure time to open, then close and measure time to close again
            time_to_open = measure(pin_open, pin_check_open)
            time_to_close = measure(pin_close, pin_check_closed)
        elif not is_closed and is_opened:
            # door is open, measure time to close, then open and measure time to open again
            time_to_close = measure(pin_close, pin_check_closed)
            time_to_open = measure(pin_open, pin_check_open)
        else:
            # door is somewhere, close it, then open, then close again
            _ = measure(pin_close, pin_check_closed) #ignore time
            time_to_open = measure(pin_open, pin_check_open)
            time_to_close = measure(pin_close, pin_check_closed)
        
        return time_to_close, time_to_open     

    statsFilename = Path(__file__).with_suffix(".stats")

    #try reading file
    try:
        with open(statsFilename) as infile:
            data = json.load(infile)
    except EnvironmentError:
        data = {}

    needMeasurementGarage = False
    needMeasurementFence = False

    if not data:
        # Data is empty, have to meassure
        if CONFIG["garage"]["enabled"]: needMeasurementGarage = True
        if CONFIG["fence"]["enabled"]: needMeasurementFence = True
    else:
        # Data is not empty, check if all vars exists
        print("Found old measurement data")

        if CONFIG["garage"]["enabled"]:
            if "garage_door" in data:
                if not "close_time" in data["garage_door"]:
                    needMeasurementGarage = True
                if not "open_time" in data["garage_door"]:
                    needMeasurementGarage = True
            else:
                needMeasurementGarage = True
        if CONFIG["fence"]["enabled"]:
            if "fence_gate" in data:
                if not "close_time" in data["fence_gate"]:
                    needMeasurementFence = True
                if not "open_time" in data["fence_gate"]:
                    needMeasurementFence = True
            else:
                needMeasurementFence = True
    
    # measurment is needed
    if needMeasurementGarage:
        print("No movement times for garage door, measure...")
        data["garage_door"] = {}
        data["garage_door"]["close_time"], data["garage_door"]["open_time"] = measureMovingTime("garage")
    if needMeasurementFence:
        print("No movement times for fence gate, measure...")
        data["fence_gate"] = {}
        data["fence_gate"]["close_time"], data["fence_gate"]["open_time"] = measureMovingTime("fence")

    # move to new dict to clean up data and to stat cache
    measurements = {}
    if CONFIG["garage"]["enabled"]:
        measurements["garage_door"] = {}
        measurements["garage_door"]["close_time"] = data["garage_door"]["close_time"]
        measurements["garage_door"]["open_time"] = data["garage_door"]["open_time"]

        STAT_CACHE["garage"]["close_time"] = data["garage_door"]["close_time"]
        STAT_CACHE["garage"]["open_time"] = data["garage_door"]["open_time"]

    if CONFIG["fence"]["enabled"]:
        measurements["fence_gate"] = {}
        measurements["fence_gate"]["close_time"] = data["fence_gate"]["close_time"]
        measurements["fence_gate"]["open_time"] = data["fence_gate"]["open_time"]

        STAT_CACHE["fence"]["close_time"] = data["fence_gate"]["close_time"]
        STAT_CACHE["fence"]["open_time"] = data["fence_gate"]["open_time"]

    # write to file if new data is available
    if needMeasurementFence or needMeasurementGarage:
        with open(statsFilename, 'w') as outfile:
            json.dump(measurements, outfile, indent=4, sort_keys=True)

def main():

    #my_logger = get_logger("my module name")
    #my_logger.debug("a debug message")
    if not read_config():
        print("Config file not present or broken")
        sys.exit()

    initialize_cache()

    if not initialize_gpio():
        print("GPIO ports cannot initialized")
        sys.exit()

    #Signal Handler for interrupting the loop
    signal.signal(signal.SIGINT, signal_handler)        

    getMovingTimes()

    mqttclient = mqttInitialize()
    
    while loopEnabled:

        #if connection was not successful, try it in next loop again
        if not mqttConnect(mqttclient): pass

        #push home assistant autodiscovery
        mqttPushConfig(mqttclient)

        if mqttclient.connected_flag: 
            mqttGetAndPushCPUTemp(mqttclient)
            mqttGetAndPushDoorState(mqttclient)

        time.sleep(5.0 - time.time() % 5.0)
    
    #end while loopEnabled
    
    #after stoping the loop disconnect and quit
    mqttDisconnect(mqttclient)

if __name__ == "__main__":
   main()