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
# $File: omniswitch_topology_utils.py$

# $Build: OONP_H_R01_6$

# $Date: 05/06/2014 12:10:39$

# $Author: vapoonat$

#
#

import os
import sys

#from neutron.openstack.common import cfg
from oslo.config import cfg


from neutron.plugins.omniswitch import omniswitch_constants as omni_const
from neutron.plugins.omniswitch.omniswitch_restful_driver import OmniSwitchRestfulDriver
from neutron.plugins.omniswitch.omniswitch_telnet_driver import OmniSwitchTelnetDriver

OMNI_PLUGIN_CONFIG_FILE = "/etc/neutron/plugins/omniswitch/omniswitch_network_plugin.ini"

class OmniSwitchTopologyUtils(object):

    """ 
    Name:        OmniSwitchTopologyUtils
    Description: OpenStack Neutron plugin for Alcatel-Lucent OmniSwitch Data networking
                 devices.

    Details:     Some utilities that can be used outside of Neutron plug-in to perform
                 operations on the topology used by the plug-in. The topology information
                 is obtained from the plug-in config file. The default location of the 
                 file is "/etc/neutron/plugins/omniswitch/omniswitch_network_plugin.ini".

                 Following are the utilities that are available...
                 1) setup_initial : it performs the necessary initial config on the topology 
                 2) clear_initial : it removes all the initial config on the topology
                 3) clear_tenant : it removes all the tenant config done by the openstack on the topolgy
                 4) save : it saves all the config done on the topology
    """

    edge_device_list = [] # list of omni devices from 'omni_network_plugin.ini' file
    edge_ddi_list = {} # list of device driver instances (ddi) corresponding to each 
                       # of the device in edge_device_list

    core_device_list = [] # list of omni core devices from 'omni_network_plugin.ini' file
    core_ddi_list = {} # list of device driver instances (ddi) corresponding to each
                       # of the device in core_device_list

    host_classification = '' # host VM classification method
    core_network_config = '' # core network config mechanism

    switch_access_method = '' # OS6900 and OS10K access method

    sections = {}
    configFile = None

    def __init__(self, confFile):
        self.configFile = confFile
        self._load_config()
        self._load_edge_ddi()
        self._load_core_ddi()
      

    def _parse_config_file(self):
        if self.configFile == None :
           print "Please specify a configuration file!"
           return

        parser = cfg.ConfigParser(self.configFile, self.sections)
        try:
            parser.parse()
        except IOError:
            print "File %s not found!!!" % OMNI_PLUGIN_CONFIG_FILE
        print "Config file <%s> parsed successfully!" % OMNI_PLUGIN_CONFIG_FILE
        """
        #print self.sections
        for section in self.sections:
            print "SECTION: %s" % section
            print "SECTION ITEMS: %s" % self.sections[section]
            for name in self.sections[section]:
                print "SECTION ITEM's Key: %s" % name 
                print "SECTION ITEM's Value: %s" % self.sections[section][name]
        """


    def _get_config(self, section, name):
        rvalue = []
        items = []
        if section in self.sections:
            if name in self.sections[section]:
                items = self.sections[section][name][0].split(',')
                for i in range(0, len(items)):
                    rvalue.append(items[i].strip())
                return rvalue
        #raise KeyError
        return None

    def _load_config(self):

        self._parse_config_file()

        #### OMNI_EDGE_DEVICES
        device_list = self._get_config("DEVICE", "omni_edge_devices")
        for device in device_list:
            self.edge_device_list.append(device.strip().split(':'))


        #### OMNI_CORE_DEVICES
        device_list = self._get_config("DEVICE", "omni_core_devices")
        if device_list == ['']:
            device_list = None
        if device_list is not None:
            for device in device_list:
                self.core_device_list.append(device.strip().split(':'))

        #### HOST_CLASSIFICATION
        self.host_classification = self._get_config("DEVICE", "host_classification")[0]

        #### CORE_NETWORK_CONFIG
        self.core_network_config = self._get_config("DEVICE", "core_network_config")[0]

        #### SWITCH_ACCESS_METHOD
        self.switch_access_method = self._get_config("DEVICE", "switch_access_method")[0]

        ### parse NETWORK_VLAN_RANGES from the config file
        self._parse_network_vlan_ranges()


    def _load_edge_ddi(self):
        #for device in self.edge_device_list:
        #    for i in range(0,len(device)):
        #        LOG.info("VAD: OMNI_DEV: device tems: <%s>, len = %d", device[i], len(device[i].strip()))
        for device in self.edge_device_list:
            drv_type = self._get_driver_type(device[omni_const.OMNI_CFG_DEV_TYPE])
            if drv_type == omni_const.OMNISWITCH_7XX or drv_type == omni_const.OMNISWITCH_8XX :
                if self.switch_access_method == omni_const.OMNI_CFG_SWITCH_ACCESS_REST :
                    self.edge_ddi_list.setdefault(device[omni_const.OMNI_CFG_DEV_IP],
                              OmniSwitchRestfulDriver(device[omni_const.OMNI_CFG_DEV_IP],
                                                     device[omni_const.OMNI_CFG_DEV_LOGIN],
                                                     device[omni_const.OMNI_CFG_DEV_PASSWORD]))
                else:
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

    def _load_core_ddi(self):
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

    def initial_config(self):
        config = True # True means it applies the config
        print "Applying One-time config on the OmniSwitches!. Please wait...\n"
        if self.core_network_config == omni_const.OMNI_CFG_CORE_MVRP :
            self._config_mvrp(config)
        self._config_unp(config)
        print "\nOne-time config on the OmniSwitches completed!."

    def clear_initial_config(self):
        config = False # False means it removs the config
        print "Removing One-time config from the OmniSwitches!. Please wait...\n"
        if self.core_network_config == omni_const.OMNI_CFG_CORE_MVRP :
            self._config_mvrp(config)
        self._config_unp(config)
        print "\nOne-time config on the OmniSwitches have been removed!."

    def clear_tenant_config(self):
        vlan_ids = self._get_vlan_ids()
        #print vlan_ids
        for device in self.edge_device_list:
            print "Clearing tenant configs in %s\nIt will take several minutes... please wait...\n" % device[omni_const.OMNI_CFG_DEV_IP]
            self.edge_ddi_list[device[omni_const.OMNI_CFG_DEV_IP]].clear_config(vlan_ids)
            print "Tenant Configs cleared in  %s\n" % device[omni_const.OMNI_CFG_DEV_IP]


    def save_core_config(self):
        for device in self.core_device_list:
            self.core_ddi_list[device[omni_const.OMNI_CFG_DEV_IP]].save_config()
            print "Config saved and syncronized in %s" % device[omni_const.OMNI_CFG_DEV_IP]

    def save_edge_config(self):
        for device in self.edge_device_list:
            self.edge_ddi_list[device[omni_const.OMNI_CFG_DEV_IP]].save_config()
            print "Config saved and syncronized in %s" % device[omni_const.OMNI_CFG_DEV_IP]

    def save_config(self):
        print "Saving and Syncronizing configs in OmniSwitches given in the config file..."
        self.save_core_config()
        self.save_edge_config()


    def _config_mvrp(self, config=True):
        if_list = []
        for device in self.core_device_list:
            if config:
                self.core_ddi_list[device[omni_const.OMNI_CFG_DEV_IP]].enable_mvrp()
                print "MVRP enabled on %s" % device[omni_const.OMNI_CFG_DEV_IP]
            else:
                self.core_ddi_list[device[omni_const.OMNI_CFG_DEV_IP]].disable_mvrp()
                print "MVRP disabled on %s" % device[omni_const.OMNI_CFG_DEV_IP]
            if device[omni_const.OMNI_CFG_DEV_CORE_IF].strip() :
                if_list = device[omni_const.OMNI_CFG_DEV_CORE_IF].split(' ')
                for port in if_list:
                    if config :
                        self.core_ddi_list[device[omni_const.OMNI_CFG_DEV_IP]].enable_mvrp(port)
                        print "MVRP enabled on %s of %s" %(port, device[omni_const.OMNI_CFG_DEV_IP])
                    else:
                        self.core_ddi_list[device[omni_const.OMNI_CFG_DEV_IP]].disable_mvrp(port)
                        print "MVRP disabled on %s of %s" %(port, device[omni_const.OMNI_CFG_DEV_IP])
 
        for device in self.edge_device_list:
            if config:
                self.edge_ddi_list[device[omni_const.OMNI_CFG_DEV_IP]].enable_mvrp()
                print "MVRP enabled on %s" % device[omni_const.OMNI_CFG_DEV_IP]
            else:
                self.edge_ddi_list[device[omni_const.OMNI_CFG_DEV_IP]].disable_mvrp()
                print "MVRP disabled on %s" % device[omni_const.OMNI_CFG_DEV_IP]
            if device[omni_const.OMNI_CFG_DEV_EDGE2CORE_IF].strip() :
                if_list = device[omni_const.OMNI_CFG_DEV_EDGE2CORE_IF].split(' ')
                for port in if_list:
                    if config:
                        self.edge_ddi_list[device[omni_const.OMNI_CFG_DEV_IP]].enable_mvrp(port)
                        print "MVRP enabled on %s of %s" %(port, device[omni_const.OMNI_CFG_DEV_IP])
                    else:
                        self.edge_ddi_list[device[omni_const.OMNI_CFG_DEV_IP]].disable_mvrp(port)
                        print "MVRP disabled on %s of %s" %(port, device[omni_const.OMNI_CFG_DEV_IP])


    def _config_unp(self, config=True):
        for device in self.edge_device_list:
            if device[omni_const.OMNI_CFG_DEV_EDGE2COMPUTE_IF].strip() :
                if_list = device[omni_const.OMNI_CFG_DEV_EDGE2COMPUTE_IF].split(' ')
                for port in if_list:
                    if config:
                        self.edge_ddi_list[device[omni_const.OMNI_CFG_DEV_IP]].enable_unp(port)
                        print "UNP enabled on %s of %s" %(port, device[omni_const.OMNI_CFG_DEV_IP])
                    else:
                        self.edge_ddi_list[device[omni_const.OMNI_CFG_DEV_IP]].disable_unp(port)
                        print "UNP disabled on %s of %s" %(port, device[omni_const.OMNI_CFG_DEV_IP])

    # Utility routines
    def _get_driver_type(self, switch_type):
        if switch_type == omni_const.OMNISWITCH_OS6860 :
            return omni_const.OMNISWITCH_8XX
        if switch_type == omni_const.OMNISWITCH_OS6900 or \
           switch_type == omni_const.OMNISWITCH_OS10K:
            return omni_const.OMNISWITCH_7XX
        elif switch_type == omni_const.OMNISWITCH_OS6850E or \
             switch_type == omni_const.OMNISWITCH_OS6855 or \
             switch_type == omni_const.OMNISWITCH_OS6450 or \
             switch_type == omni_const.OMNISWITCH_OS9000:
            return omni_const.OMNISWITCH_6XX

    def _parse_network_vlan_ranges(self):
        self.network_vlan_ranges = {}
        for entry in self._get_config("PLUGIN", "network_vlan_ranges"):
            entry = entry.strip()
            if ':' in entry:
                try:
                    physical_network, vlan_min, vlan_max = entry.split(':')
                    self._add_network_vlan_range(physical_network.strip(),
                                                 int(vlan_min),
                                                 int(vlan_max))
                except ValueError as ex:
                    print "Invalid network VLAN range: '%s' - %s. " %(entry, ex)
                    sys.exit(1)
            else:
                self._add_network(entry)
        #print "Network VLAN ranges = %s" % self.network_vlan_ranges

    def _add_network_vlan_range(self, physical_network, vlan_min, vlan_max):
        self._add_network(physical_network)
        self.network_vlan_ranges[physical_network].append((vlan_min, vlan_max))

    def _add_network(self, physical_network):
        if physical_network not in self.network_vlan_ranges:
            self.network_vlan_ranges[physical_network] = []

    def _get_vlan_ids(self):
        for physical_network, vlan_ranges in self.network_vlan_ranges.iteritems():
            vlan_ids = set()
            for vlan_range in vlan_ranges:
                vlan_ids |= set(xrange(vlan_range[0], vlan_range[1] + 1))
            return vlan_ids # for now only one phy network is considered


if __name__ == "__main__":

    if len(sys.argv) == 1 :
        print "Usage: python omniswitch_topology_utils.py {setup_initial | clear_initial | clear_tenant | save} [config_file]"
        sys.exit(1)

    if len(sys.argv) == 2 :
        print "Warning: Plug-in config file is not specified!"
        if os.path.exists(OMNI_PLUGIN_CONFIG_FILE):
            print "Warning: Using default config file <%s>" % OMNI_PLUGIN_CONFIG_FILE
            topo_utils = OmniSwitchTopologyUtils(OMNI_PLUGIN_CONFIG_FILE)
        else:
            print "ERROR: Default config file <%s> is also not found!" % OMNI_PLUGIN_CONFIG_FILE
            print "Please run the script with plug-in config file!"
            print "Usage: python omniswitch_topology_utils.py {setup_initial | clear_initial | clear_tenant | save} [config_file]"
            sys.exit(1)


    if len(sys.argv) == 3 :
        if os.path.exists(sys.argv[2]):
            topo_utils = OmniSwitchTopologyUtils(sys.argv[2])
        else:
            print "ERROR: Config file <%s> not present!!!" % sys.argv[2]
            print "Usage: python omniswitch_topology_utils.py {setup_initial | clear_initial | clear_tenant | save} [config_file]"
            sys.exit(1)

    if sys.argv[1] == 'setup_initial' :
        topo_utils.initial_config()
    elif sys.argv[1] == 'clear_initial' :
        topo_utils.clear_initial_config()
    elif sys.argv[1] == 'clear_tenant' :
        topo_utils.clear_tenant_config()
    elif sys.argv[1] == 'save' :
        topo_utils.save_config()
    else:
        print "ERROR: Invalid option <%s> specified!!!" % sys.argv[1]
        print "Usage: python omniswitch_topology_utils.py {setup_initial | clear_initial | clear_tenant | save} [config_file]"
        sys.exit(1)

    
