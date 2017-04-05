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

#TODO: If a message cannot be relayed, email results.

MODEM_DEVICE = "/dev/ttyS0"
BAUD_RATE = 115200

class SMSModem(threading.Thread):

    def __init__(self):
        super(SMSModem, self).__init__()
        self.ser = None
        self.bot = None
        self.exit = False
        self.new_messages = False
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

    def decode_msg(self, msg):
        try:
            msg = msg.strip()
            return msg.decode('hex').decode('iso-8859-1',errors='replace').encode('utf-8')
        except TypeError:
            pass

        return msg.decode('iso-8859-1',errors='replace').encode('utf8')

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

    def set_bot(self, bot):
        self.bot = bot

    def process_messages(self):
        if not self.bot:
            log.info("Not connected to Telegram, skipping catch up.")
            return

        stored_cmds = []
        new_messages = True

        self.ser.write('AT+CMGF=1\n')
        self.wait_for()

        self.ser.write('AT+CMGL="ALL"\n')
        self.new_messages = False
        while new_messages:
            new_messages = False
            while True:
                line = self.ser.readline()
                if not line:
                    log.error("timeout, process messages")
                    break
                line = line.strip()
                log.info("r>%s" % line)

                if line.startswith("OK"):
                    break

                if line.startswith("+CMGL:"):
                    data = line.split(',')
                    cmd, index = data[0].split(' ')
                    sender = data[2][1:-1]
                    dt = data[4][1:] + " " + data[5][0:-1]
                    msg = self.decode_msg(self.ser.readline())
                    log.info("S> %s, %s, %s: %s" % (index, sender, dt, msg))

                    try:
                        bot.sendMessage(chat_id=config.CHAT_ID, text="%s @ %s\n%s" % (sender, dt, msg))
                        stored_cmds.append('AT+CMGD=%s\n' % index)
                    except telegram.TelegramError as e:
                        log.error("Cannot send message to telegram." + str(e))

                if line.startswith("+CMTI:"):
                    new_messages = True

            for cmd in stored_cmds:
                self.ser.write(cmd)
                self.wait_for()

    def send_message(self, msg):
        self.modem.send_message(msg)

    def next_message(self):
        while True:
            msg = self.modem.next_message()
            if not msg:
                return None
            
            if msg.startswith("+CMTI:"):
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

        log.info("wait timeout")
        return False

    def handle_telegram_message(self, msg):
        p = re.compile('^6[0-9]{8}:')
        m = p.match(msg)
        if m:
            log.info("T>" + msg)
            out = 'AT+CMGS="+34' + m.group()[:-1] + '"\n'
            self.ser.write(out.encode('utf-8'))
            self.wait_for(">")
            out = ('%s' % msg[11:]) + chr(26)
            self.ser.write(out.encode('utf-8'))
            log.info("T> sent")
        else:
            # TODO: Split messages 
            if msg != "/start":
                bot.sendMessage(config.CHAT_ID, text="You suck. Invalid message format, yo! Use <ES mobile number>: <message>")
                bot.sendMessage(config.CHAT_ID, text="you said: '%s'" % msg)

    def run(self):
        self.modem.start()

        self.send_message("ATE0")
        self.wait_for()

        self.send_message('AT+CMGF=1')
        self.wait_for()

        self.send_message('AT+CMGL="ALL"')
        self.wait_for()
        log.info("OK!")

    def crappy_crap(self):

        next_id = None
        line = ""
        while True:

            # If we haven't started receiving a line (idle), do event loop stuff
            if not line:
                if self.new_messages:
                    self.process_messages()

                try:
                    updates = bot.getUpdates(offset=next_id)
                except telegram.TelegramError as e:
                    print "Telegram error: ", str(e)
                except Exception as e:
                    print "general error: ", str(e)
                for u in updates:
                    self.handle_telegram_message(u.message.text)
                    next_id = u.update_id + 1

logging.basicConfig(filename=os.path.join(os.path.dirname(os.path.realpath(__file__)), 'gateway.log'),level=logging.INFO)
log = logging

sms = SMS()
if not sms.modem.open(MODEM_DEVICE, BAUD_RATE):
    sys.exit(-1)

bot = telegram.Bot(token=config.ACCESS_TOKEN)
logging.info("Logged in as %s." % bot.first_name)

bot.sendMessage(chat_id=config.CHAT_ID, text="mayhem sms gateway bot at your service!")
sms.set_bot(bot)

logging.info("Modem ready for communication!")
try:
    sms.run()
except KeyboardInterrupt:
    print "keyboard interrupt"
    pass

sms.modem.stop()
