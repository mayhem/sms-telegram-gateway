#!/usr/bin/env python

import sys
import os
import re
import logging
import threading
import serial
import telegram
from time import sleep, time
import config
from Queue import Queue, Empty
from urllib2 import HTTPError

#TODO: If a message cannot be relayed, email results.

MODEM_DEVICE = "/dev/ttyS0"
BAUD_RATE = 115200

class SMSModem(threading.Thread):

    def __init__(self):
        super(SMSModem, self).__init__()
        self.ser = None
        self.bot = None
        self.exit = False
        self.in_q = Queue()

    def open(self, device, baud_rate):
        try:
            self.ser = self.ser = serial.Serial(device,
                baud_rate, 
                bytesize=serial.EIGHTBITS, 
                parity=serial.PARITY_NONE, 
                stopbits=serial.STOPBITS_ONE,
                timeout=.1)
        except serial.serialutil.SerialException as e:
            log.error("Cannot open serial port to Fona 800. " + str(e))
            return False

        return True

    def next_message(self):
        try:
            return self.in_q.get()
        except Empty:
            return None

    def send_message(self, msg):
        log.info("write:%s" % msg)
        self.ser.write(msg + "\n")

    def stop(self):
        self.exit = True

    def run(self):
        line = ""
        while not self.exit:
            ch = self.ser.read(1)
            if not ch:
                if line:
                    self.in_q.put(line)
                    line = ""
                continue

            if ch == '\r':
                continue

            if ch == '\n':
                self.in_q.put(line)
                line = ""
                continue

            line += ch

        log.info("end thread")


class SMS(object):

    def __init__(self):
        self.modem = SMSModem()
        self.new_messages = True

    def set_bot(self, bot):
        self.bot = bot

    def decode_message(self, msg):

        # this is just a test to see if it is all hex
        try:
            msg = msg.strip()
            msg.decode('hex')
        except TypeError:
            return unicode(msg.decode('iso-8859-1',errors='replace'))

        out = ""
        while len(msg):
            out += (msg[2:4]+msg[0:2]).decode('hex').decode('utf-16')
            msg = msg[4:]

        return unicode(out)

    def send_message(self, msg):
        self.modem.send_message(msg)

    def next_message(self):
        while True:
            msg = self.modem.next_message()
            if not msg:
                return None
            
            log.info("next:%s" % msg)
            if msg.startswith("+CMTI:"):
                log.info("new message!")
                self.new_messages = True
                continue

            return msg

    def wait_for(self, str="OK"):
        timeout = time() + 1
        while time() < timeout:
            msg = self.next_message()
            if not msg:
                continue

            log.info("read:%s" % msg)
            if msg.startswith(str):
                return True

            if msg.startswith("ERROR"):
                return False

        log.info("wait timeout")
        return False

    def handle_telegram_message(self, msg):
        p = re.compile('^\+[0-9]+:')
        m = p.match(msg)
        if m:
            num = m.group()[:-1]
            log.info("T>" + msg)
            out = 'AT+CMGS="' + num + '"'
            self.send_message(out.encode('utf-8'))
            self.wait_for(">")
            out = ('%s' % msg[14:]) + chr(26)
            self.send_message(out.encode('utf-8'))
            log.info("T> '%s' sent" % out.encode('utf-8'))
        else:
            if msg != "/start":
                bot.sendMessage(config.CHAT_ID, text="You suck. Invalid message format, yo! Use <ES mobile number>: <message>")
                bot.sendMessage(config.CHAT_ID, text="you said: '%s'" % msg)

    def run(self):
        # TODO: add error handling
        self.modem.start()

        self.send_message("ATE0")
        self.wait_for()

        self.send_message('AT+CMGF=1')
        self.wait_for()

        self.send_message('AT+CNMI=2,2,0,0,0')
        self.wait_for()

        next_id = None
        while True:
            try:
                updates = bot.getUpdates(offset=next_id)
            except telegram.TelegramError as e:
                log.error("Telegram error: %s" % str(e))
                sleep(3)
                continue
            except Exception as e:
                log.error("general error: %s" % str(e))
                sleep(3)
                continue
            except HTTPError as e:
                log.error("http error: %s" % str(e))
                sleep(3)
                continue

            for u in updates:
                self.handle_telegram_message(u.message.text)
                next_id = u.update_id + 1

            if not self.new_messages:
                continue

            self.send_message('AT+CMGL="ALL"')
            stored_cmds = []
            while True:
                msg = self.next_message()
                if not msg:
                    continue

                log.info("read:%s" % msg)

                if msg.startswith("+CMGL:"):
                    data = msg.split(',')
                    cmd, index = data[0].split(' ')
                    sender = data[2][1:-1]
                    dt = data[4][1:] + " " + data[5][0:-1]
                    msg = self.decode_message(self.next_message())
                    log.info("S> %s, %s, %s: %s" % (index, sender, dt, msg))

                    try:
                        bot.sendMessage(chat_id=config.CHAT_ID, text="%s @ %s\n%s" % (sender, dt, msg))
                        stored_cmds.append('AT+CMGD=%s' % index)
                    except telegram.TelegramError as e:
                        log.error("Cannot send message to telegram." + str(e))

                if msg.startswith("OK"):
                    for cmd in stored_cmds:
                        self.send_message(cmd)
                        self.wait_for()
                    self.new_messages = False
                    break


logging.basicConfig(filename=os.path.join(os.path.dirname(os.path.realpath(__file__)), 'gateway.log'),level=logging.INFO)
log = logging

sms = SMS()
if not sms.modem.open(MODEM_DEVICE, BAUD_RATE):
    sys.exit(-1)

bot = telegram.Bot(token=config.ACCESS_TOKEN)
logging.info("Logged in as %s." % bot.first_name)

# TODO: re-add this
#bot.sendMessage(chat_id=config.CHAT_ID, text="mayhem sms gateway bot at your service!")
sms.set_bot(bot)

logging.info("Modem ready for communication!")
try:
    sms.run()
except KeyboardInterrupt:
    print "keyboard interrupt"
    pass

sms.modem.stop()
