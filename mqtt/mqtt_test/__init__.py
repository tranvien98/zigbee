import logging
import ujson as json
import utime
import uasyncio as asyncio
from umqtt.simple import MQTTClient
from micropython import const
from core.db_pan_nodes import DBPanNodes
import picoweb
import time
globalPan = None
HONYAR_NETWORK_ADDRESS = 0x4441
HONYAR = 3163294935805788
DOOR = 6066005700592132
DOOR_NETWORK_ADDRESS = 0xB071
MOTION_NETWORK_ADDRESS = 0x7877
MOTION_IEEE_ADDRESS = 6066005700993056
displayNodes = DBPanNodes()
list_nodes = displayNodes.getPanNodesInfo()


def sendMessage(ieeeAddr, switch_id, msg):
    global globalPan
    state = msg
    if state.upper() == 'ON':
        payload = [0x11, 0x00, 0x01]
    elif state.upper() == 'OFF':
        payload = [0x11, 0x00, 0x00]
    nodeId = ieeeAddr
    clusterId = 0x0006
    DstEndpoint = switch_id
    SrcEndpoint = 0x01
    return globalPan.sendRawData(
        nodeId=nodeId,
        payload=payload,
        nwkAddr=None,  # use nodeId
        clusterId=clusterId,
        DstEndpoint=DstEndpoint,
        SrcEndpoint=SrcEndpoint
    )


def qs_parse(qs):
    parameters = {}
    ampersandSplit = qs.split("&")
    for element in ampersandSplit:
        equalSplit = element.split("=")
        parameters[equalSplit[0]] = equalSplit[1]
    return parameters


class MqttClient:

    MQTT_HOST = "mx.javis.io"
    MQTT_PORT = 8883
    HONYAR_ID = HONYAR
    DOOR_ID = DOOR
    MOTION_ID = MOTION_IEEE_ADDRESS
    UNIQUE_ID = 'dev:1:a1daa56f-08b0-477a-9d0c-f09887994817'
    DEFAULT_KEEPALIVE = const(60)
    KEEP_ALIVE_THRESHOLD = const(5)

    def __init__(self, loop, log, callback=None):
        self.loop = loop
        self.log = log
        self.subscribeCallback = callback
        self.sn = self.UNIQUE_ID
        self.honyar_sn = self.HONYAR_ID
        self.door_sn = self.DOOR_ID
        self.client = None
        self.topicSubOperation = "1/MC30AEA4D7D4D0/{}_{}/set"
        self.topicPubState = "1/MC30AEA4D7D4D0/{}_{}/state"
        self.mqttLive = False
        self.log.info('MQTT init')

    def _clientInit(self):
        self.client = MQTTClient(client_id=self.sn,
                                 server=self.MQTT_HOST,
                                 port=self.MQTT_PORT,
                                 user='MC30AEA4D7D4D0',
                                 password='WsWAE/dVieUQHPn9jtBCYw==',
                                 keepalive=DEFAULT_KEEPALIVE,
                                 ssl=True,
                                 ssl_params={})

    def _clientConnect(self):
        self.log.debug('MQTT connecting...')
        try:
            self.client.connect()
            self.log.info('MQTT live!')
            self.mqttLive = True
            return True
        except Exception as e:
            print(e)
            self.log.exception(e, 'could not establish MQTT connection')
            return False

    def _subscribeTopic(self):
        try:
            # set a handler for incoming messages
            self.client.set_callback(self._msgReceivedCallback)
            self.client.subscribe(
                topic=self.topicSubOperation.format(self.honyar_sn, 1), qos=0)
            self.client.subscribe(
                topic=self.topicSubOperation.format(self.honyar_sn, 2), qos=0)
            self.client.subscribe(
                topic=self.topicSubOperation.format(self.honyar_sn, 3), qos=0)
            self.log.info('subscribe [%s]', self.topicSubOperation)
            print('subscribe [%s]', self.topicSubOperation)
        except Exception as e:
            self.log.exception(e, 'subscribe fail')

    def _resetPingTimer(self):
        self.pingCountdown = DEFAULT_KEEPALIVE

    def _ping(self):
        ''' do a MQTT ping before keepalive period expires '''
        self.pingCountdown -= 1
        if self.pingCountdown < KEEP_ALIVE_THRESHOLD:
            self.log.debug('mqtt ping...')
            self.client.ping()
            self._resetPingTimer()

    def _connectAttempt(self):
        if self._clientConnect():
            self._subscribeTopic()
            self._resetPingTimer()
            return True
        else:
            return False

    def _msgReceivedCallback(self, topic, msg):
        if self.subscribeCallback is not None:
            self.subscribeCallback(topic, msg)

    def mqttIsLive(self):
        return self.mqttLive

    def publishMsg(self, ieeeAddr, index, msg):
        try:
            if ieeeAddr == self.HONYAR_ID:
                topic = self.topicPubState.format(self.honyar_sn, index)
                self.log.info("publish: topic[%s] msg[%s]", topic, msg)
                print("publish: topic[%s] msg[%s]", topic, msg)
                self.client.publish(topic=topic, msg=msg, qos=0)
            elif ieeeAddr == self.DOOR_ID:
                topic = "1/MC30AEA4D7D4D0/{}/state".format(self.door_sn)
                self.client.publish(topic=topic, msg=msg, qos=0)
            elif ieeeAddr == self.MOTION_ID:
                topic = "1/MC30AEA4D7D4D0/{}/state".format(self.MOTION_ID)
                self.client.publish(topic=topic, msg=msg, qos=0)
        except Exception as e:
            self.log.exception(e, 'publish fail')

    async def taskMqttWorker(self):
        reconnectAttemptBackoff = 1  # don't try too hard, use backoff
        self._connectAttempt()
        print("", time.time())
        while True:
            try:
                self.client.check_msg()  # if there is a message, _msgReceivedCallback will be called
                self._ping()
                reconnectAttemptBackoff = 1
                await asyncio.sleep(0.1)
            except Exception as e:
                self.log.exception(e, 'MQTT check message problem')
                self.mqttLive = False
                if not self._connectAttempt():
                    reconnectAttemptBackoff *= 2  # don't retry too fast, this will abuse the server
                    if reconnectAttemptBackoff > 64:
                        reconnectAttemptBackoff = 64
                    self.log.debug('reconnect attempt backoff: %ds',
                                   reconnectAttemptBackoff)
                    await asyncio.sleep(reconnectAttemptBackoff)

    def start(self):
        self._clientInit()
        self.loop.create_task(self.taskMqttWorker())


class WebServer():
    def __init__(self):
        self.log = logging.getLogger("Web Server")
        self.run()

    def run(self):
        webapp = picoweb.WebApp(__name__)

        @webapp.route("/list_nodes", methods=['GET', 'POST', 'DELETE'])
        def index(req, resp):
            method = req.method
            self.log.debug("Method %s called", method)
            if method == "GET":
                queryString = req.qs
                if queryString != "":
                    parameters = qs_parse(queryString)
                    self.log.debug(str(parameters))
                    yield from picoweb.start_response(resp)
                    if 'nodeid' in parameters:
                        if parameters['nodeid'].isdigit():
                            if int(parameters['nodeid']) in list_nodes:
                                yield from resp.awrite(str({int(parameters['nodeid']): list_nodes[int(parameters['nodeid'])]}))
                            else:
                                yield from resp.awrite("Cannot get Node with ID: " + parameters['nodeid'])
                        else:
                            yield from resp.awrite("NodeID not Valid")
                else:
                    yield from picoweb.start_response(resp)
                    yield from resp.awrite(str(list_nodes))
            elif method == 'POST':
                yield from req.read_form_data()
                nodeid = req.form['nodeid']
                namenode = req.form['name']
                for node in list_nodes:
                    if str(node) == nodeid:
                        list_nodes[node]["name"] = namenode
                displayNodes.setPanNodesInfo(list_nodes)
                yield from picoweb.start_response(resp)
                yield from resp.awrite("Add name of Node " + nodeid)
            elif method == 'DELETE':
                yield from req.read_form_data()
                nodeid = req.form['nodeid']
                try:
                    del list_nodes[nodeid]
                except:
                    pass
                displayNodes.setPanNodesInfo(list_nodes)
                self.log.debug("Deleted node: %s", nodeid)
                yield from picoweb.start_response(resp)
                yield from resp.awrite("Deleted Node " + str(nodeid))

        @webapp.route('/control', methods=['POST'])
        def control_device(req, resp):
            yield from req.read_form_data()
            print("______control__________")
            print(req.__dict__)
            print("----------------------------")
            print(req.form)
            nodeid = int(req.form['nodeid'])
            state = req.form['state']
            switch_id = int(req.form['idx'])
            sendMessage(int(nodeid), switch_id, state)
            yield from picoweb.start_response(resp)
            yield from resp.awrite("Controlled Device " + str(nodeid))
        # self.log.info("Running on 0.0.0.0:5050...")
        webapp.run(debug=True, host="0.0.0.0", port=5050)


class App:
    def __init__(self, mgr, loop, pan):
        self.log = logging
        self.mc = MqttClient(loop, self.log, self.onMsgReceived)
        self.pan = pan
        self.remember = 0
        global globalPan
        globalPan = pan
        self.mc.start()
        self.web = WebServer()
        # loop.create_task(self.taskPublishTest())
        mgr.setSetupPressedCallback(self.onSetupPressed)
        self.pan.setAppNodeJoinCallback(self.onNodeJoin)
        self.pan.setAppDataReceiveCallback(self.onDataReceive)
        self.loop = loop

    def onSetupPressed(self):
        self.log.info('setup button pressed')
        if self.pan:
            self.pan.permitDeviceJoin(60)

    def onNodeJoin(self, rawData, n):
        self.log.info('node joined/rejoined')
        self.log.debug("SrcAddr %s", hex(n.SrcAddr))
        self.log.debug("NwkAddr %s", hex(n.NwkAddr))
        self.log.debug("IEEEAddr %s", hex(n.IEEEAddr))  # nodeId
        self.nodeId = n.IEEEAddr
        self.log.debug("Capabilities %s", hex(n.Capabilities))

    def onMsgReceived(self, topic, msg):
        s_topic = topic.decode()
        s_msg = msg.decode()
        if s_topic.find("set") != -1:
            self.remember = 1
            # print(s_topic)
            ieeeAddr = s_topic.split("/")[2].split("_")[0]
            switch_id = s_topic.split("/")[2].split("_")[1]
            self.mc.publishMsg(int(ieeeAddr), int(switch_id), s_msg)
            # print("start time:", time.time())
            sendMessage(int(ieeeAddr), int(switch_id), s_msg)
            self.log.info("received: topic[%s] msg[%s]", s_topic, s_msg)
            print("received: topic[%s] msg[%s]", s_topic, s_msg)

    def onDataReceive(self, rawData, n):
        self.log.debug("Len# %d", n.Len)
        # print("Data#", end=' ')
        i = 0
        while i < n.Len:
            # print('0x{0:0{1}X}'.format(n.Data[i], 2), end=' ')
            i += 1
        self.loop.create_task(self.taskDataReceived(n))  # run a asyncio task

    async def taskDataReceived(self, n):
        for node_id in list_nodes:
            if list_nodes[node_id]['nwkAddr'] == n.SrcAddr:
                ieeeAddr = node_id
                break
        # print("endtime",time.timezone)
        # print("time end:", time.time())
        if n.SrcAddr == HONYAR_NETWORK_ADDRESS:
            index = n.SrcEndpoint
            if n.Data[6] == 0:
                # cập nhật trạng thái trên HA
                print(self.remember)
                if self.remember != 1:
                    self.mc.publishMsg(ieeeAddr, index, "off")
                self.remember = 0
                # cập nhật trạng thái hub
                if 'state' not in list_nodes[ieeeAddr]:
                    states = {
                        "switch1": "unknown",
                        "switch2": "unknown",
                        "switch3": "unknown",
                    }
                    states["switch" + str(index)] = "off"
                    list_nodes[ieeeAddr]['state'] = states
                else:
                    list_nodes[ieeeAddr]['state']["switch" +
                                                  str(index)] = "off"
            elif n.Data[6] == 1:
                print(self.remember)
                if self.remember != 1:
                    self.mc.publishMsg(ieeeAddr, index, "on")
                self.remember = 0
                if 'state' not in list_nodes[ieeeAddr]:
                    states = {
                        "switch1": "unknown",
                        "switch2": "unknown",
                        "switch3": "unknown",
                    }
                    states["switch" + str(index)] = "on"
                    list_nodes[ieeeAddr]['state'] = states
                else:
                    list_nodes[ieeeAddr]['state']["switch" + str(index)] = "on"
        elif n.SrcAddr == DOOR_NETWORK_ADDRESS:  # door sensor
            index = None
            if n.Data[6] == 0:
                state = "off"
                self.mc.publishMsg(ieeeAddr, index, state)
                list_nodes[ieeeAddr]['state'] = "off"

            else:
                state = "on"
                self.mc.publishMsg(ieeeAddr, index, state)
                list_nodes[ieeeAddr]['state'] = "on"

        elif n.SrcAddr == MOTION_NETWORK_ADDRESS:  # motion sensor
            index = None
            if n.Data[6] == 0:
                state = "off"
                self.mc.publishMsg(ieeeAddr, index, state)
                list_nodes[ieeeAddr]['state'] = "off"

            else:
                state = "on"
                self.mc.publishMsg(ieeeAddr, index, state)
                list_nodes[ieeeAddr]['state'] = "on"
        # print("time end:", time.time())
        # self.log.info("time end:", time.time())
        # print(list_nodes)
        displayNodes.setPanNodesInfo(list_nodes)
