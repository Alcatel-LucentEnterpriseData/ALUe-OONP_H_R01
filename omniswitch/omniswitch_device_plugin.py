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
# $File: omniswitch_device_plugin.py$

# $Build: OONP_H_R01_6$

# $Date: 05/06/2014 12:10:39$

# $Author: vapoonat$

#
#

import logging
import os
import sys
import importlib
import thread
import threading
import time

from neutron.api.v2 import attributes
from neutron.db import db_base_plugin_v2
from neutron.openstack.common import context
#from neutron.openstack.common import cfg
from oslo.config import cfg
from neutron.openstack.common import importutils

from neutron.plugins.omniswitch import omniswitch_constants as omni_const
from neutron.plugins.omniswitch.omniswitch_restful_driver import OmniSwitchRestfulDriver
from neutron.plugins.omniswitch.omniswitch_telnet_driver import OmniSwitchTelnetDriver
from neutron.plugins.omniswitch.omniswitch_db_v2 import OmniDB


LOG = logging.getLogger(__name__)

device_opts = [
    cfg.ListOpt('omni_edge_devices', default=[], help=""),
    cfg.ListOpt('omni_core_devices', default=[], help=""),
    cfg.StrOpt('dhcp_server_interface', default='',help=""),
    cfg.StrOpt('host_classification', default='VLAN_TAG',help=""),
    cfg.StrOpt('core_network_config', default='MVRP',help=""),
    cfg.StrOpt('switch_access_method', default='REST',help=""),
    cfg.StrOpt('switch_vlan_name_prefix', default='OpenStack',help=""),
    cfg.IntOpt('switch_save_config_interval', default=1800,help=""),
]


class OmniSwitchDevicePluginV2(db_base_plugin_v2.NeutronDbPluginV2):

    """ 
    Name:        OmniSwitchDevicePluginV2 
    Description: OpenStack Neutron plugin for Alcatel-Lucent OmniSwitch Data networking
                 devices.

    Details:     It is one of the device plugin in the OmniSwitch multi-plugin design. 
                 This implements the Neutron Network APIs (ver 2.0) for OmniSwitch 
                 devices. This is instantiated by the OmniSwitchNetworkPluginV2 which is 
                 core plugin for Neutron server. This uses the device specific 
                 communication mechanism for interfacing with different types of 
                 OmniSwitch devices. 
    """

    edge_device_list = [] # list of omni devices from 'omni_network_plugin.ini' file
    edge_ddi_list = {} # list of device driver instances (ddi) corresponding to each 
                       # of the device in edge_device_list

    core_device_list = [] # list of omni core devices from 'omni_network_plugin.ini' file
    core_ddi_list = {} # list of device driver instances (ddi) corresponding to each
                       # of the device in core_device_list

    dhcp_service = [] # details of the edge switch which is connected to network node where dhcp-server is running
    dhcp_if_inst = None

    host_classification = '' # host VM classification method
    core_network_config = '' # core network config mechanism

    switch_access_method = '' # OS6900 and OS10K access method
    switch_vlan_name_prefix = '' # custom string to be used in vlan name
    switch_save_config_interval = 0 # interval(in secs) at which the config will be saved in the switches 

    db_option = None
    init_config_applied = None

    edge_config_changed = 0
    core_config_changed = 0

    def __init__(self):
        self._load_config()
        self._load_edge_ddi()
        self._load_core_ddi()
        self._load_dhcp_if_inst()
        self._start_save_config_thread()

    def initialize(self, db_obj):
        self.omni_db_obj = db_obj

    def _load_config(self, conf_file=None):
        """
        loads the OmniSwitch device list from the config file and instantiates 
        the appropriate device specific driver to communicate with it.
        """
        self.configFile = conf_file
        cfg.CONF.register_opts(device_opts, "DEVICE")

        #### OMNI_EDGE_DEVICES
        for device in cfg.CONF.DEVICE.omni_edge_devices:
            self.edge_device_list.append(device.strip().split(':'))

        #### OMNI_CORE_DEVICES
        if cfg.CONF.DEVICE.omni_core_devices != [] and \
           cfg.CONF.DEVICE.omni_core_devices != [''] :
            for device in cfg.CONF.DEVICE.omni_core_devices:
                self.core_device_list.append(device.strip().split(':'))

        #### DHCP_SERVER_INTERFACE
        self.dhcp_service = cfg.CONF.DEVICE.dhcp_server_interface.strip().split(':')
        if self.dhcp_service == [] or \
           self.dhcp_service == [''] :
            self.dhcp_service = None

        #### HOST_CLASSIFICATION
        self.host_classification = cfg.CONF.DEVICE.host_classification.strip()

        #### CORE_NETWORK_CONFIG
        self.core_network_config = cfg.CONF.DEVICE.core_network_config.strip()

        #### SWITCH_ACCESS_METHOD
        self.switch_access_method = cfg.CONF.DEVICE.switch_access_method.strip()

        ### SWITCH_VLAN_NAME_PREFIX
        self.switch_vlan_name_prefix = cfg.CONF.DEVICE.switch_vlan_name_prefix.strip()

        ### SWITCH_VLAN_NAME_PREFIX
        self.switch_save_config_interval = cfg.CONF.DEVICE.switch_save_config_interval
        if self.switch_save_config_interval < 600 :
            self.switch_save_config_interval = 600

        LOG.info("_load_config done!")


    def _load_edge_ddi(self):
        for device in self.edge_device_list:
            drv_type = self._get_driver_type(device[omni_const.OMNI_CFG_DEV_TYPE])
            if drv_type == omni_const.OMNISWITCH_7XX or drv_type == omni_const.OMNISWITCH_8XX :
                if self.switch_access_method == omni_const.OMNI_CFG_SWITCH_ACCESS_REST :
                    self.edge_ddi_list.setdefault(device[omni_const.OMNI_CFG_DEV_IP], 
                              OmniSwitchRestfulDriver(device[omni_const.OMNI_CFG_DEV_IP],
                                                     device[omni_const.OMNI_CFG_DEV_LOGIN],
                                                     device[omni_const.OMNI_CFG_DEV_PASSWORD]))
                else :
                    self.edge_ddi_list.setdefault(device[omni_const.OMNI_CFG_DEV_IP],
                              OmniSwitchTelnetDriver(device[omni_const.OMNI_CFG_DEV_IP], False, 
                                                     device[omni_const.OMNI_CFG_DEV_LOGIN],
                                                     device[omni_const.OMNI_CFG_DEV_PASSWORD]))

            elif drv_type == omni_const.OMNISWITCH_6XX :
                self.edge_ddi_list.setdefault(device[omni_const.OMNI_CFG_DEV_IP],
                              OmniSwitchTelnetDriver(device[omni_const.OMNI_CFG_DEV_IP], True,
                                                     device[omni_const.OMNI_CFG_DEV_LOGIN],
                                                     device[omni_const.OMNI_CFG_DEV_PASSWORD],
                                                     device[omni_const.OMNI_CFG_DEV_PROMPT]))

            if self.edge_ddi_list[device[omni_const.OMNI_CFG_DEV_IP]]:
                self.edge_ddi_list[device[omni_const.OMNI_CFG_DEV_IP]].set_config(self.switch_vlan_name_prefix)


        LOG.info("_load_edge_ddi done!")

    def _load_core_ddi(self):
        if len(self.core_device_list) == 0 :
            return

        for device in self.core_device_list:
            drv_type = self._get_driver_type(device[omni_const.OMNI_CFG_DEV_TYPE])
            if drv_type == omni_const.OMNISWITCH_7XX or drv_type == omni_const.OMNISWITCH_8XX :
                if self.switch_access_method == omni_const.OMNI_CFG_SWITCH_ACCESS_REST :
                    self.core_ddi_list.setdefault(device[omni_const.OMNI_CFG_DEV_IP],
                             OmniSwitchRestfulDriver(device[omni_const.OMNI_CFG_DEV_IP],
                                                     device[omni_const.OMNI_CFG_DEV_LOGIN],
                                                     device[omni_const.OMNI_CFG_DEV_PASSWORD]))
                else:
                    self.core_ddi_list.setdefault(device[omni_const.OMNI_CFG_DEV_IP],
                              OmniSwitchTelnetDriver(device[omni_const.OMNI_CFG_DEV_IP], False,
                                                     device[omni_const.OMNI_CFG_DEV_LOGIN],
                                                     device[omni_const.OMNI_CFG_DEV_PASSWORD]))
            elif drv_type == omni_const.OMNISWITCH_6XX :
                self.core_ddi_list.setdefault(device[omni_const.OMNI_CFG_DEV_IP],
                              OmniSwitchTelnetDriver(device[omni_const.OMNI_CFG_DEV_IP], True,
                                                     device[omni_const.OMNI_CFG_DEV_LOGIN],
                                                     device[omni_const.OMNI_CFG_DEV_PASSWORD],
                                                     device[omni_const.OMNI_CFG_DEV_PROMPT]))

            if self.core_ddi_list[device[omni_const.OMNI_CFG_DEV_IP]]:
                self.core_ddi_list[device[omni_const.OMNI_CFG_DEV_IP]].set_config(self.switch_vlan_name_prefix)
        
        LOG.info("_load_core_ddi done!")

    def _load_dhcp_if_inst(self):
        if self.dhcp_service == None:
            return
        drv_type = self._get_driver_type(self.dhcp_service[omni_const.OMNI_CFG_DEV_TYPE])
        if drv_type == omni_const.OMNISWITCH_7XX or drv_type == omni_const.OMNISWITCH_8XX :
            if self.switch_access_method == omni_const.OMNI_CFG_SWITCH_ACCESS_REST :
                self.dhcp_if_inst = OmniSwitchRestfulDriver(self.dhcp_service[omni_const.OMNI_CFG_DEV_IP],
                                                     self.dhcp_service[omni_const.OMNI_CFG_DEV_LOGIN],
                                                     self.dhcp_service[omni_const.OMNI_CFG_DEV_PASSWORD])
            else:
                self.dhcp_if_inst = OmniSwitchTelnetDriver(self.dhcp_service[omni_const.OMNI_CFG_DEV_IP], False,
                                                     self.dhcp_service[omni_const.OMNI_CFG_DEV_LOGIN],
                                                     self.dhcp_service[omni_const.OMNI_CFG_DEV_PASSWORD])
        elif drv_type == omni_const.OMNISWITCH_6XX :
            self.dhcp_if_inst = OmniSwitchTelnetDriver(self.dhcp_service[omni_const.OMNI_CFG_DEV_IP], True,
                                                     self.dhcp_service[omni_const.OMNI_CFG_DEV_LOGIN],
                                                     self.dhcp_service[omni_const.OMNI_CFG_DEV_PASSWORD],
                                                     self.dhcp_service[omni_const.OMNI_CFG_DEV_PROMPT])

        if self.dhcp_if_inst :
            self.dhcp_if_inst.set_config(self.switch_vlan_name_prefix)

        LOG.info("_load_dhcp_if_inst done!") 
        
    def _start_save_config_thread(self):
        SaveConfigThread(self).start()

    def _config_mvrp(self):
        if_list = []
        LOG.info("_config_mvrp called!")
        for device in self.core_device_list:
            self.core_ddi_list[device[omni_const.OMNI_CFG_DEV_IP]].enable_mvrp()
            if device[omni_const.OMNI_CFG_DEV_CORE_IF].strip() :
                if_list = device[omni_const.OMNI_CFG_DEV_CORE_IF].split(' ')
                for port in if_list:
                    self.core_ddi_list[device[omni_const.OMNI_CFG_DEV_IP]].enable_mvrp(port)
 
        for device in self.edge_device_list:
            self.edge_ddi_list[device[omni_const.OMNI_CFG_DEV_IP]].enable_mvrp()
            if device[omni_const.OMNI_CFG_DEV_EDGE2CORE_IF].strip() :
                if_list = device[omni_const.OMNI_CFG_DEV_EDGE2CORE_IF].split(' ')
                for port in if_list:
                    self.edge_ddi_list[device[omni_const.OMNI_CFG_DEV_IP]].enable_mvrp(port)
        LOG.info("_config_mvrp done!")

    def _config_mvrp_core(self, enable):
        if_list = []
        for device in self.core_device_list:
            if enable == 1:
                self.core_ddi_list[device[omni_const.OMNI_CFG_DEV_IP]].enable_mvrp()
                time.sleep(2)
            elif enable == 0:
                self.core_ddi_list[device[omni_const.OMNI_CFG_DEV_IP]].disable_mvrp()
                time.sleep(2)

    def _config_unp(self):
        for device in self.edge_device_list:
            if device[omni_const.OMNI_CFG_DEV_EDGE2COMPUTE_IF].strip() :
                if_list = device[omni_const.OMNI_CFG_DEV_EDGE2COMPUTE_IF].split(' ')
                for port in if_list:
                    self.edge_ddi_list[device[omni_const.OMNI_CFG_DEV_IP]].enable_unp(port)
        LOG.info("_config_unp done!")

    def _config_vpa(self, vlan_id, action, net_name=''):
        if_list = []
        if self.core_network_config == omni_const.OMNI_CFG_CORE_VPA :
            for device in self.core_device_list:
                if device[omni_const.OMNI_CFG_DEV_CORE_IF].strip() :
                    if action == omni_const.OMNI_CFG_CREATE :
                        self.core_ddi_list[device[omni_const.OMNI_CFG_DEV_IP]].create_vlan_locked(vlan_id, net_name)
                    elif action == omni_const.OMNI_CFG_DELETE :
                        self.core_ddi_list[device[omni_const.OMNI_CFG_DEV_IP]].delete_vlan_locked(vlan_id)

                    if_list = device[omni_const.OMNI_CFG_DEV_CORE_IF].split(' ')
                    for port in if_list:
                        if action == omni_const.OMNI_CFG_CREATE :
                            self.core_ddi_list[device[omni_const.OMNI_CFG_DEV_IP]].create_vpa(vlan_id, port)
                        #elif action == omni_const.OMNI_CFG_DELETE :
                        #    #self.core_ddi_list[device[omni_const.OMNI_CFG_DEV_IP]].delete_vpa(vlan_id, port)

            for device in self.edge_device_list:
                if device[omni_const.OMNI_CFG_DEV_EDGE2CORE_IF].strip() :
                    if_list = device[omni_const.OMNI_CFG_DEV_EDGE2CORE_IF].split(' ')
                    for port in if_list:
                        if action == omni_const.OMNI_CFG_CREATE :
                            self.edge_ddi_list[device[omni_const.OMNI_CFG_DEV_IP]].create_vpa(vlan_id, port)
                        #elif action == omni_const.OMNI_CFG_DELETE :
                        #    self.edge_ddi_list[device[omni_const.OMNI_CFG_DEV_IP]].delete_vpa(vlan_id, port)
        return True  ### _config_vpa


    def apply_initial_config(self):
        if self.core_network_config == omni_const.OMNI_CFG_CORE_MVRP :
            self._config_mvrp()
        self._config_unp()
        self.save_config()

    def save_core_config(self, immediate=0):
        if immediate == 0:
            self.core_config_changed = 1
            return

        for device in self.core_device_list:
            ddi_obj = self.core_ddi_list[device[omni_const.OMNI_CFG_DEV_IP]]
            ret = self._invoke_driver_api(ddi_obj, "save_config", [])
            #self.core_ddi_list[device[omni_const.OMNI_CFG_DEV_IP]].save_config()

        self.core_config_changed = 0 
        return

    def save_edge_config(self, immediate=0):
        if immediate == 0:
            self.edge_config_changed = 1
            return

        for device in self.edge_device_list:
            ddi_obj = self.edge_ddi_list[device[omni_const.OMNI_CFG_DEV_IP]]
            ret = self._invoke_driver_api(ddi_obj, "save_config", [])
            #self.edge_ddi_list[device[omni_const.OMNI_CFG_DEV_IP]].save_config()

        self.edge_config_changed = 0
        return
    
    def save_config(self):
        if self.core_config_changed == 1:
            self.save_core_config(1)
     
        if self.edge_config_changed == 1:
            self.save_edge_config(1)

    """ Neutron Core API 2.0 """

    def create_network_bulk(self, context, networks):
        pass


    def create_network(self, context, network):
        ret = True
        binding = self.omni_db_obj.get_network_binding(context.session, network['id'])
        vlan_id = binding.segmentation_id
        network_name = network['network']['name']

        if self.core_network_config == omni_const.OMNI_CFG_CORE_MVRP :
            self._config_mvrp_core(0) # disable mvrp in core before start creating network

        for ddi_key, ddi_obj in self.edge_ddi_list.items():
            #if ddi_obj.create_network(vlan_id) :
            if self._invoke_driver_api(ddi_obj, "create_network", [vlan_id, network_name]):
                if self.host_classification == omni_const.OMNI_CFG_HOST_CLASS_VTAG :
                    ret = self._invoke_driver_api(ddi_obj, "create_port", [binding.segmentation_id])
                    #ret = ddi_obj.create_port(binding.segmentation_id)
            else:
                ret = False

            if not ret:
                # some error in create network, roll back network creation
                self.delete_network(context, network['id']) #vad: optimize only for that switch
                self.save_edge_config() 
                return False

        if self.core_network_config == omni_const.OMNI_CFG_CORE_MVRP :
            self._config_mvrp_core(1) # enable mvrp in core after network creation

        if self.core_network_config == omni_const.OMNI_CFG_CORE_VPA :
            if not self._config_vpa(vlan_id, 1, network_name):
                # some error in vpa creation, roll back network creation
                self.delete_network(context, network['id'])
                self.save_edge_config()
                return False
            else:
                self.save_core_config()

        if self.dhcp_if_inst :
            if not self.dhcp_if_inst.create_vpa(vlan_id, self.dhcp_service[omni_const.OMNI_CFG_DHCP_SERVER_IF]):
                # some error in vpa creation for dhcp, roll back network creation
                self.delete_network(context, network['id'])
                self.save_edge_config() # vad: optimize only for that switch
                return False

        self.save_edge_config()
        return True

    def update_network(self, context, id, network):
        pass

    def delete_network(self, context, id):
        # first delete the default dhcp server ie, remove the corresponding mac-rule from the switch
        filters = {'network_id': [id]}
        openports = super(OmniSwitchDevicePluginV2, self).get_ports(context, filters)
        if len(openports) == 1 :
            if openports[0]['device_owner'] == 'network:dhcp' :
                self.delete_port(context, openports[0]['id'], 1)
            else:
                LOG.info("network:dhcp port not found for the network %s", id)
        elif len(openports) > 1 :
            LOG.info("More than one port exists!. Can not delete network %s", id)
            return False
          
        # then delete the network ie, delete the corresponding vlan
        binding = self.omni_db_obj.get_network_binding(context.session, id)
        vlan_id = binding.segmentation_id

        if self.core_network_config == omni_const.OMNI_CFG_CORE_VPA :
            if not self._config_vpa(vlan_id, 0):
                return False
            else:
                self.save_core_config()

        for ddi_key, ddi_obj in self.edge_ddi_list.items():
            if self.host_classification == omni_const.OMNI_CFG_HOST_CLASS_VTAG :
                #ddi_obj.delete_port(vlan_id)
                self._invoke_driver_api(ddi_obj, "delete_port", [vlan_id])
            #ddi_obj.delete_network(vlan_id)
            self._invoke_driver_api(ddi_obj, "delete_network", [vlan_id])

        #if self.dhcp_if_inst :
        #    self.dhcp_if_inst.delete_vpa(vlan_id, self.dhcp_server_if)
        self.save_edge_config()
        return True

    def get_network(self, context, id, fields=None): 
        pass

    def get_networks(self, context, filters=None, fields=None):
        pass

    def get_networks_count(self, context, filters=None):
        pass

    def create_subnet_bulk(self, context, subnets):
        pass

    def create_subnet(self, context, subnet):
        pass

    def update_subnet(self, context, id, subnet):
        pass

    def delete_subnet(self, context, id):
        subnet = super(OmniSwitchDevicePluginV2, self).get_subnet(context, id)
        if subnet is None:
            LOG.info("delete_subnet: subnet %s not found!", id)
            return False

        network_filters = {'network_id':[subnet['network_id']]}
        subnet_count = super(OmniSwitchDevicePluginV2, self).get_subnets_count(context, network_filters)
        #LOG.info("VAD: delete_subnet: subnet = %s, net_id = %s, subnet_count=%s", subnet, subnet['network_id'], subnet_count)
        if subnet_count > 1 :
            return True;

        # first delete the default dhcp server ie, remove the corresponding mac-rule from the switch
        filters = {'fixed_ips': {'subnet_id':[id]}}
        openports = super(OmniSwitchDevicePluginV2, self).get_ports(context, filters)
        if len(openports) == 1 :
            if openports[0]['device_owner'] == 'network:dhcp' :
                self.delete_port(context, openports[0]['id'], 1)
            else:
                LOG.info("network:dhcp port not found for the subnet %s", id)
        elif len(openports) > 1 :
            LOG.info("More than one port exists!. Can not delete subnet %s", id)
            return False
        return True

    def get_subnet(self, context, id, fields=None):
        pass

    def get_subnets(self, context, filters=None, fields=None):
        pass

    def get_subnets_count(self, context, filters=None):
        pass

    def create_port_bulk(self, context, ports):
        pass

    def create_port(self, context, port):
        binding = self.omni_db_obj.get_network_binding(context.session, port['network_id'])
        for ddi_key, ddi_obj in self.edge_ddi_list.items(): 
            if self.host_classification == omni_const.OMNI_CFG_HOST_CLASS_MAC :
                if not self._invoke_driver_api(ddi_obj, "create_port", [binding.segmentation_id, port['mac_address']]):
                    return False
                """
                if not ddi_obj.create_port(binding.segmentation_id, port['mac_address']):
                    return False
                """

        self.save_edge_config()
        return True

    def update_port(self, context, id, port):
        pass

    def delete_port(self, context, id, force=0):
        openport = super(OmniSwitchDevicePluginV2, self).get_port(context, id)
        # if it is a dhcp server it is already taken care while deleting network
        if openport['device_owner'] == 'network:dhcp' and force == 0:
            return True

        if self.host_classification != omni_const.OMNI_CFG_HOST_CLASS_MAC :
            return True

        binding = self.omni_db_obj.get_network_binding(context.session, openport['network_id'])
        for ddi_key, ddi_obj in self.edge_ddi_list.items():
            self._invoke_driver_api(ddi_obj, "delete_port", [binding.segmentation_id, openport['mac_address']])
            #ddi_obj.delete_port(binding.segmentation_id, openport['mac_address'])

        self.save_edge_config()
        return True

    def get_port(self, context, id, fields=None):
        pass

    def get_ports(self, context, filters=None, fields=None):
        pass

    def get_ports_count(self, context, filters=None):
        pass

    # Utility routines
    def _get_driver_type(self, switch_type):
        if switch_type == omni_const.OMNISWITCH_OS6860:
            return omni_const.OMNISWITCH_8XX
        elif switch_type == omni_const.OMNISWITCH_OS6900 or \
           switch_type == omni_const.OMNISWITCH_OS10K:
            return omni_const.OMNISWITCH_7XX
        elif switch_type == omni_const.OMNISWITCH_OS6850E or \
             switch_type == omni_const.OMNISWITCH_OS6855 or \
             switch_type == omni_const.OMNISWITCH_OS6450 or \
             switch_type == omni_const.OMNISWITCH_OS9000:
            return omni_const.OMNISWITCH_6XX

    def _invoke_driver_api(self, drvobj, function_name, args):
        #return thread.start_new_thread(getattr(drvobj, function_name), tuple(args))
        return getattr(drvobj, function_name)(*args)



### Save config thread class

class SaveConfigThread(threading.Thread):
    plugin_obj = None
    def __init__(self, plugin_obj):
        self.plugin_obj = plugin_obj
        threading.Thread.__init__(self)
        self.event = threading.Event()

    def run(self):
        if self.plugin_obj is None:
            LOG.info("Plugin Object is Null, SaveConfigThread is terminated!")
            self.stop()
            return

        while not self.event.is_set():
            #print "do something %s" % time.asctime(time.localtime(time.time()))
            #self.event.wait( 1 )
            self.plugin_obj.save_config()
            #LOG.info("run: %s", time.asctime(time.localtime(time.time())))
            self.event.wait(self.plugin_obj.switch_save_config_interval)

    def stop(self):
        self.event.set()

