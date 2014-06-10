#!/bin/env python 
#
#  Copyright 2014 Alcatel-Lucent Enterprise.
#
#  Licensed under the Apache License, Version 2.0 (the "License"); you may not use this file
#  except in compliance with the License. You may obtain a copy of the License at
#
#  http://www.apache.org/licenses/LICENSE-2.0
#
#  Unless required by applicable law or agreed to in writing, software distributed under the License
#  is distributed on an "AS IS" BASIS, WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND,
#  either express or implied. See the License for the specific language governing permissions
#  and limitations under the License.
#
#
# $File: omniswitch_telnet_driver.py$

# $Build: OONP_H_R01_6$

# $Date: 05/06/2014 12:10:39$

# $Author: vapoonat$

#
#

import logging
import os
import sys
import traceback
import telnetlib
import time
import re

import thread
import threading

from neutron.plugins.omniswitch import omniswitch_constants as omni_const

LOG = logging.getLogger(__name__)

class OmniSwitchTelnetDriver(object):

    """ 
    Name:        OmniSwitchTelnetDriver 
    Description: OmniSwitch device driver to communicate with AOS 6x devices such as OS6850E,
                 OS6855, OS6450 and OS6250 etc.

    Details:     It is used by OmniSwitchDevicePluginV2 to perform the necessary configuration on the physical 
                 switches as response to OpenStack networking APIs. This driver is used only for above mentioned 
                 AOS 6x devices. 
    """

    telnetObj = None
    switch_ip = None
    switch_login = None
    switch_password = None
    switch_prompt = None
    is6x = True
    threadLock = None
    _init_done = False

    ### user configs
    switch_vlan_name_prefix = ''


    def __init__(self, ip, bool6x, login='admin', password='switch', prompt='->'):
        self.is6x = bool6x
        self.switch_ip = ip.strip()
        if len(self.switch_ip) == 0 :
            LOG.info("Init Error! Must provide a valid IP address!!!")
            return

        self.switch_login = login.strip()
        if len(self.switch_login) == 0 :
            self.switch_login = 'admin'

        self.switch_password = password.strip()
        if len(self.switch_password) == 0 :
            self.switch_password = 'switch'

        self.switch_prompt = prompt.strip()
        if len(self.switch_prompt) == 0 :
            self.switch_prompt = '->'

        self.threadLock = threading.Lock()
        self._init_done = True

    def set_config(self, vlan_name_prefix):
        self.switch_vlan_name_prefix = vlan_name_prefix

    def connect(self):
        if self._init_done == False :
            LOG.info("Driver is not initialized!!!")
            return False
       
        self.telnetObj = telnetlib.Telnet(self.switch_ip, 23, 10)
        #self.telnetObj.set_debuglevel(10)

        self.telnetObj.read_until("login :", omni_const.OMNI_CLI_SMALL_TIMEOUT)
        self.telnetObj.write(self.switch_login + "\n")
        self.telnetObj.read_until("assword : ", omni_const.OMNI_CLI_SMALL_TIMEOUT)
        self.telnetObj.write(self.switch_password + "\n")
        if(self.telnetObj.read_until(self.switch_prompt, omni_const.OMNI_CLI_PROMPT_TIMEOUT) == None):
            LOG.info("Connection to %s failed!", self.switch_ip)
            return False

        return True
 

    def disconnect(self):
        if self.telnetObj :
            self.telnetObj.close()
        self.telnetObj = None

    def isConnected(self):
        if(self.telnetObj == None):
            return False

        self.telnetObj.write("\n\n")
        if(self.telnetObj.read_until(self.switch_prompt, omni_const.OMNI_CLI_PROMPT_TIMEOUT) == None):
            return False
        else:
            return True

    def sendCommand(self, command):
        #LOG.info("sendCommand: <%s> to %s entry!", command, self.switch_ip)
        self.threadLock.acquire(1)
        #LOG.info("sendCommand: <%s> to %s lock acquired!", command, self.switch_ip)

        if(self.isConnected() == False):
            if(self.connect() == False):
                self.threadLock.release()
                #LOG.info("sendCommand: <%s> to %s lock released!", command, self.switch_ip) 
                #LOG.info("sendCommand: <%s> to %s exit!", command, self.switch_ip)
                return False

        #if(self.isConnected() == True):
        if self.telnetObj :
            self.telnetObj.write(command)
            self.telnetObj.write("\n")
            ret = self.telnetObj.read_until("ERROR", 1) #omni_const.OMNI_CLI_SMALL_TIMEOUT)
            #LOG.info("VAD: sendCommand: <%s> to %s, RETURNED = <%s>", command, self.switch_ip, ret)
            if re.search('ERROR', ret) == None :
                # this additional read makes command execute is completed
                self.telnetObj.read_until(self.switch_prompt, omni_const.OMNI_CLI_SMALL_TIMEOUT)
                LOG.info("sendCommand: <%s> to %s success!", command, self.switch_ip)
                self.threadLock.release()
                #LOG.info("sendCommand: <%s> to %s lock released!", command, self.switch_ip)
                #LOG.info("sendCommand: <%s> to %s exit!", command, self.switch_ip)
                return True
            else:
                ret = self.telnetObj.read_until('\n', omni_const.OMNI_CLI_SMALL_TIMEOUT)
                LOG.info("sendCommand: <%s> failed! in %s, ret = ERROR%s", command, self.switch_ip, ret)
                self.threadLock.release()
                #LOG.info("sendCommand: <%s> to %s lock released!", command, self.switch_ip)
                #LOG.info("sendCommand: <%s> to %s exit!", command, self.switch_ip)
                return False
        else:
            LOG.info("Could not connect to %s", self.switch_ip)
            LOG.info("sendCommand: <%s> failed!", command)
            self.threadLock.release()
            #LOG.info("sendCommand: <%s> to %s lock released!", command, self.switch_ip)
            #LOG.info("sendCommand: <%s> to %s exit!", command, self.switch_ip)
            return False

    def create_vpa(self, vlan_id, slotport, args=None):
        if self.is6x :
            return self.sendCommand('vlan '+str(vlan_id)+' 802.1q '+str(slotport))
        else:
            if len(slotport.split('/')) == 1:
                return self.sendCommand('vlan '+str(vlan_id)+' members linkagg '+str(slotport)+' tagged')
            else:
                return self.sendCommand('vlan '+str(vlan_id)+' members port '+str(slotport)+' tagged')
            
    def delete_vpa(self, vlan_id, slotport, args=None):
        if self.is6x :
            return self.sendCommand('no 802.1q '+str(slotport))
        else:
            if len(slotport.split('/')) == 1:
                return self.sendCommand('no vlan '+str(vlan_id)+' members linkagg '+str(slotport))
            else:
                return self.sendCommand('no vlan '+str(vlan_id)+' members port '+str(slotport))

    def create_vlan_locked(self, vlan_id, net_name=''):
        return self.create_vlan(vlan_id, net_name)

    def create_vlan(self, vlan_id, net_name=''):
        vlan_name = str(self.switch_vlan_name_prefix+'-'+net_name+'-'+str(vlan_id))
        #return self.sendCommand('vlan '+str(vlan_id)+' name '+'OpenStack-'+str(vlan_id))
        return self.sendCommand(str('vlan '+str(vlan_id)+' name '+vlan_name))

    def delete_vlan_locked(self, vlan_id):
        return self.delete_vlan(vlan_id)

    def delete_vlan(self, vlan_id):
        return self.sendCommand('no vlan '+str(vlan_id))

    def create_unp_vlan(self, vlan_id, args=None):
        return self.sendCommand('unp name '+'OpenStack-UNP-'+str(vlan_id)+' vlan '+str(vlan_id))

    def create_unp_macrule(self, vlan_id, mac, args=None):
        return self.sendCommand('unp classification mac-address '+str(mac)+' unp-name '+'OpenStack-UNP-'+str(vlan_id))

    def get_unp_macrule(self, args=None):
        command = 'show unp classification mac-rule'
        if(self.isConnected() == False):
            if(self.connect() == False):
                return False

        if(self.isConnected() == True):
            self.telnetObj.write(command)
            self.telnetObj.write("\n")
            ret = self.telnetObj.read_until("ERROR", omni_const.OMNI_CLI_SMALL_TIMEOUT)
            if re.search('ERROR', ret) == None :
                mac_pattern = re.compile('\w\w:\w\w:\w\w:\w\w:\w\w:\w\w')
                return mac_pattern.findall(ret)
            else:
                ret = self.telnetObj.read_until('\n', omni_const.OMNI_CLI_SMALL_TIMEOUT)
                LOG.info("sendCommand: <%s> failed!, ret = ERROR%s", command, ret)
                return False
        else:
            LOG.info("Could not connect to %s", self.switch_ip)
            LOG.info("sendCommand: <%s> failed!", command)
            return False

        pass

    def create_unp_vlanrule(self, vlan_id):
        return self.sendCommand('unp classification vlan-tag '+str(vlan_id)+' unp-name '+'OpenStack-UNP-'+str(vlan_id))

    def delete_unp_vlan(self, vlan_id):
        return self.sendCommand('no unp name '+'OpenStack-UNP-'+str(vlan_id))

    def delete_unp_macrule(self, vlan_id, mac):
        return self.sendCommand('no unp classification mac-address '+str(mac))

    def delete_unp_vlanrule(self, vlan_id):
        return self.sendCommand('no unp classification vlan-tag '+str(vlan_id))

    def enable_stp_mode_flat(self):
        if self.is6x :
            return self.sendCommand('bridge mode flat')
        else:
            return self.sendCommand('spantree mode flat')

    def disable_stp_mode_flat(self):
        if self.is6x :
            return self.sendCommand('bridge mode 1x1')
        else:
            return self.sendCommand('spantree mode per-vlan')

    def enable_mvrp_global(self):
        return self.sendCommand('mvrp enable')

    def disable_mvrp_global(self):
        return self.sendCommand('mvrp disable')

    def enable_mvrp_if(self, slotport):
        if len(slotport.split('/')) == 1:
            return self.sendCommand('mvrp linkagg '+str(slotport)+' enable')
        else:
            return self.sendCommand('mvrp port '+str(slotport)+' enable')

    def disable_mvrp_if(self, slotport):
        if len(slotport.split('/')) == 1:
            return self.sendCommand('mvrp linkagg '+str(slotport)+' disable')
        else:
            return self.sendCommand('mvrp port '+str(slotport)+' disable')

    def enable_mvrp(self, slotport=None):
        if slotport:
            return self.enable_mvrp_if(slotport)
        else:
            if self.enable_stp_mode_flat() == True:
                return self.enable_mvrp_global()
            else:
                return False
       
    def disable_mvrp(self, slotport=None):
        if slotport:
            return self.disable_mvrp_if(slotport)
        else:
            if self.disable_mvrp_global() == True:
                return self.disable_stp_mode_flat()
            else:
                return False

    def enable_unp(self, slotport):
        if len(slotport.split('/')) == 1:
            if self.sendCommand('unp linkagg '+str(slotport)):
                return self.sendCommand('unp linkagg '+str(slotport)+' classification enable')
        else:
            if self.sendCommand('unp port '+str(slotport)):
                return self.sendCommand('unp port '+str(slotport)+' classification enable')
        return False

    def disable_unp(self, slotport):
        if len(slotport.split('/')) == 1:
            return self.sendCommand('no unp linkagg '+str(slotport))
        else:
            return self.sendCommand('no unp port '+str(slotport))

    def write_memory_flash_synchro(self):
        return self.sendCommand('write memory flash-synchro')

    def write_memory(self):
        return self.sendCommand('write memory')

    def copy_running_certified(self):
        if self.is6x :
            return self.sendCommand('copy working certified')
        else:
            return self.sendCommand('copy running certified')

    #####  OneTouch functions for OpenStack APIs #####
    def create_network(self, vlan_id, net_name=''):
        if self.create_vlan(vlan_id, net_name) == True:
            return self.create_unp_vlan(vlan_id)
        else:
            return False   
  
    def delete_network(self, vlan_id):
        if self.delete_unp_vlan(vlan_id) == True:
            return self.delete_vlan(vlan_id)
        else:
            return False
    
    def create_port(self, vlan_id, mac=None):
        if mac :
            return self.create_unp_macrule(vlan_id, mac)
        else :
            return self.create_unp_vlanrule(vlan_id)

    def delete_port(self, vlan_id, mac=None):
        if mac :
            return self.delete_unp_macrule(vlan_id, mac)
        else :
            return self.delete_unp_vlanrule(vlan_id)

    def save_config(self):
        return self.write_memory_flash_synchro()

    def clear_config(self, vlan_ids):
        # delete mac_rules
        results = self.get_unp_macrule()
        if results and len(results):
            for i in vlan_ids:
                for mac in results:
                    self.delete_unp_macrule(0, mac)

        # delete vlan_rules and vlans
        for i in vlan_ids:
            self.delete_unp_vlanrule(i)
            self.delete_unp_vlan(i)
            self.delete_vlan(i)


    #####   Internal Utility functions #####
    # <define here>
