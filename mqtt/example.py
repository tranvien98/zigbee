import paho.mqtt.client as mqtt #import the client1
import time
############
def on_message(client, userdata, message):
    print("message received " ,str(message.payload.decode("utf-8")))
    print("message topic=",message.topic)
    print("message qos=",message.qos)
    print("message retain flag=",message.retain)
########################################
broker_address="mx.javis.io"
#broker_address="iot.eclipse.org"
print("creating new instance")
client = mqtt.Client("P1") #create new instance
client.on_message=on_message #attach function to callback
print("connecting to broker")
client.connect(broker_address, 8883, 60) #connect to broker
client.loop_start() #start the loop
client.publish("1/MC30AEA4D7D4D0/a1/state", 'hello')
# print("Subscribing to topic","hoan/test")
# client.subscribe("hoan/test")
# client.subscribe("thieu/test")
# print("Publishing message to topic","house/bulbs/bulb1")
# client.publish("house/bulbs/bulb1","OFF")
time.sleep(2) # wait
client.loop_stop() #stop the loop