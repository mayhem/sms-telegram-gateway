#!/usr/bin/env python

import sys
import os
import re
import logging

import serial
import telegram
from time import sleep
import config

#TODO: If a message cannot be relayed, email results.

MODEM_DEVICE = "/dev/ttyS0"
BAUD_RATE = 115200

class SMS(object):
    def __init(self):
        self.ser = None
        self.bot = None

    def open(self):
        try:
            self.ser = self.ser = serial.Serial(MODEM_DEVICE,
                BAUD_RATE, 
                bytesize=serial.EIGHTBITS, 
                parity=serial.PARITY_NONE, 
                stopbits=serial.STOPBITS_ONE,
                timeout=1)
        except serial.serialutil.SerialException as e:
            logging.error("Cannot open serial port to Fona 800. " + str(e))
            return False

        self.ser.write("\nAT\n")
        self.wait_for()

        logging.info("Modem ready for communication!")

        return True

    def set_bot(self, bot):
        self.bot = bot

    def decode_msg(self, msg):
        try:
            msg = msg.strip()
            return msg.decode('hex').decode('iso-8859-1',errors='replace').encode('utf-8')
        except TypeError:
            pass

        return msg.decode('iso-8859-1',errors='replace').encode('utf8')

    def process_messages(self):
        if not self.bot:
            logging.info("Not connected to Telegram, skipping catch up.")
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
                    logging.error("timeout, process messages")
                    break
                line = line.strip()
                logging.info("r>%s" % line)

                if line.startswith("OK"):
                    break

                if line.startswith("+CMGL:"):
                    data = line.split(',')
                    cmd, index = data[0].split(' ')
                    sender = data[2][1:-1]
                    dt = data[4][1:] + " " + data[5][0:-1]
                    msg = self.decode_msg(self.ser.readline())
                    print msg
                    logging.info("S> %s, %s, %s: %s" % (index, sender, dt, msg))

                    try:
                        bot.sendMessage(chat_id=config.CHAT_ID, text="%s @ %s\n%s" % (sender, dt, msg))
                        stored_cmds.append('AT+CMGD=%s\n' % index)
                    except telegram.TelegramError as e:
                        logging.error("Cannot send message to telegram." + str(e))

                if line.startswith("+CMTI:"):
                    new_messages = True

            for cmd in stored_cmds:
                self.ser.write(cmd)
                self.wait_for()

    def wait_for(self, str="OK"):
        while True:
            line = self.ser.readline()
            if not line:
                logging.error("receive timeout, wait for" + str)
                return False
            line = line.strip()
            logging.info("w>%s" % line)

            if line.startswith("+CMTI:"):
                self.new_messages = True

            if line.startswith(str):
                return True

    def handle_telegram_message(self, msg):
        p = re.compile('^6[0-9]{8}:')
        m = p.match(msg)
        if m:
            logging.info("T>" + msg)
            out = 'AT+CMGS="+34' + m.group()[:-1] + '"\n'
            self.ser.write(out.encode('utf-8'))
            self.wait_for(">")
            out = ('%s' % msg[11:]) + chr(26)
            self.ser.write(out.encode('utf-8'))
            logging.info("T> sent")
        else:
            # TODO: Split messages 
            bot.sendMessage(config.CHAT_ID, text="You suck. Invalid message format, yo! Use <ES mobile number>: <message>")
            bot.sendMessage(config.CHAT_ID, text="you said: '%s'" % msg)

    def run(self):
        next_id = None
        line = ""
        while True:
            ch = self.ser.read(1)
            if ch == '\n':
                if line.startswith("+CMTI:"):
                    self.new_messages = True
                logging.info("l>%s" % line)
                line = ""
                continue

            if ch:
                line += ch

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

sms = SMS()
if not sms.open():
    sys.exit(-1)

bot = telegram.Bot(token=config.ACCESS_TOKEN)
logging.info("Logged in as %s." % bot.first_name)

bot.sendMessage(chat_id=config.CHAT_ID, text="mayhem sms gateway bot at your service!")
sms.set_bot(bot)

sms.process_messages()
sms.run()

