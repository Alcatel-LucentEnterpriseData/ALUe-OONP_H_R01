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
# $File: omniswitch_network_plugin.py$

# $Build: OONP_H_R01_6$

# $Date: 05/06/2014 12:10:39$

# $Author: vapoonat$

#
#

import inspect
import logging
import os
import sys
import importlib

from neutron.agent import securitygroups_rpc as sg_rpc
from neutron.api.rpc.agentnotifiers import dhcp_rpc_agent_api
from neutron.api.rpc.agentnotifiers import l3_rpc_agent_api
from neutron.api.v2 import attributes

from neutron.common import constants as q_const
from neutron.common import exceptions as q_exc
from neutron.common import rpc as q_rpc
from neutron.common import topics
from neutron.db import agents_db
from neutron.db import db_base_plugin_v2
from neutron.db import l3_db
from neutron.plugins.common import constants as svc_constants
from neutron.openstack.common import context

from oslo.config import cfg
from neutron.agent.common import config
from neutron import scheduler

from neutron.openstack.common import importutils
from neutron.extensions import allowedaddresspairs as addr_pair
from neutron.extensions import extra_dhcp_opt as edo_ext
from neutron.extensions import portbindings
from neutron.extensions import providernet as provider
from neutron import manager  
from neutron.db import dhcp_rpc_base
from neutron.db import external_net_db
from neutron.db import extradhcpopt_db
from neutron.db import extraroute_db
from neutron.db import securitygroups_rpc_base as sg_db_rpc
from neutron.db import agentschedulers_db
from neutron.db import allowedaddresspairs_db as addr_pair_db
from neutron.db import l3_agentschedulers_db
from neutron.db import l3_gwmode_db
from neutron.db import l3_rpc_base
from neutron.db import portbindings_db

from neutron.openstack.common import rpc
from neutron.openstack.common.rpc import proxy

from neutron.plugins.omniswitch import omniswitch_constants as omni_const
from neutron.plugins.omniswitch import omniswitch_neutron_dbutils as omni_dbutils


LOG = logging.getLogger(__name__)

database_opts = [
    cfg.StrOpt('sql_connection', default='sqlite://'),
    cfg.IntOpt('sql_max_retries', default=-1),
    cfg.IntOpt('reconnect_interval', default=2),
]

plugin_opts = [
    cfg.StrOpt('ovs_plugin', default='',help=""),
    cfg.StrOpt('omni_plugin', default='',help=""),
    cfg.ListOpt('network_vlan_ranges', default='',
                help="List of <physical_network>:<vlan_min>:<vlan_max> "
                "or <physical_network>"),
    cfg.StrOpt('sql_connection', default='sqlite://'),
    cfg.IntOpt('sql_max_retries', default=-1),
    cfg.IntOpt('reconnect_interval', default=2),
]


class OmniRpcCallbacks(dhcp_rpc_base.DhcpRpcCallbackMixin,
                      l3_rpc_base.L3RpcCallbackMixin,
                      sg_db_rpc.SecurityGroupServerRpcCallbackMixin):

    # history
    #   1.0 Initial version
    #   1.1 Support Security Group RPC

    RPC_API_VERSION = '1.1'

    def __init__(self, notifier, db_obj):
        self.notifier = notifier
        self.omni_db_obj = db_obj

    def create_rpc_dispatcher(self):
        '''Get the rpc dispatcher for this manager.

        If a manager would like to set an rpc API version, or support more than
        one class as the target of rpc messages, override this method.
        '''
        return q_rpc.PluginRpcDispatcher([self,
                                          agents_db.AgentExtRpcCallback()])
    @classmethod
    def get_port_from_device(cls, device):
        port = omni_dbutils.get_port_from_device(device)
        if port:
            port['device'] = device
        return port


    def get_device_details(self, rpc_context, **kwargs):
        """Agent requests device details"""
        agent_id = kwargs.get('agent_id')
        device = kwargs.get('device')
        LOG.debug(_("Device %(device)s details requested from %(agent_id)s"),
                  locals())
        port = omni_dbutils.get_port(device)
        if port:
            binding = self.omni_db_obj.get_network_binding(None, port['network_id'])
            entry = {'device': device,
                     'network_id': port['network_id'],
                     'port_id': port['id'],
                     'admin_state_up': port['admin_state_up'],
                     'network_type': binding.network_type,
                     'segmentation_id': binding.segmentation_id,
                     'physical_network': binding.physical_network}
            new_status = (q_const.PORT_STATUS_ACTIVE if port['admin_state_up']
                          else q_const.PORT_STATUS_DOWN)
            if port['status'] != new_status:
                omni_dbutils.set_port_status(port['id'], new_status)
        else:
            entry = {'device': device}
            LOG.debug(_("%s can not be found in database"), device)
        return entry
                                                                                                                              
    def update_device_down(self, rpc_context, **kwargs):
        """Device no longer exists on agent"""
        # (TODO) garyk - live migration and port status
        agent_id = kwargs.get('agent_id')
        device = kwargs.get('device')
        LOG.debug(_("Device %(device)s no longer exists on %(agent_id)s"),
                  locals())
        port = omni_dbutils.get_port(device)
        if port:
            entry = {'device': device,
                     'exists': True}
            if port['status'] != q_const.PORT_STATUS_DOWN:
                # Set port status to DOWN
                omni_dbutils.set_port_status(port['id'], q_const.PORT_STATUS_DOWN)
        else:
            entry = {'device': device,
                     'exists': False}
            LOG.debug(_("%s can not be found in database"), device)
        return entry

    def update_device_up(self, rpc_context, **kwargs):
        """Device is up on agent"""
        agent_id = kwargs.get('agent_id')
        device = kwargs.get('device')
        LOG.debug(_("Device %(device)s up on %(agent_id)s"),
                  locals())
        port = omni_dbutils.get_port(device)
        if port:
            if port['status'] != q_const.PORT_STATUS_ACTIVE:
                omni_dbutils.set_port_status(port['id'],
                                          q_const.PORT_STATUS_ACTIVE)
        else:
            LOG.debug(_("%s can not be found in database"), device)

                                                                                                                              
class AgentNotifierApi(proxy.RpcProxy,
                       sg_rpc.SecurityGroupAgentRpcApiMixin):
    '''Agent side of the OmniSwitch rpc API.

    API version history:
        1.0 - Initial version.

    '''

    BASE_RPC_API_VERSION = '1.0'

    def __init__(self, topic):
        super(AgentNotifierApi, self).__init__(
            topic=topic, default_version=self.BASE_RPC_API_VERSION)
        self.topic_network_delete = topics.get_topic_name(topic,
                                                          topics.NETWORK,
                                                          topics.DELETE)
        self.topic_port_update = topics.get_topic_name(topic,
                                                       topics.PORT,
                                                       topics.UPDATE)

    def network_delete(self, context, network_id):
        self.fanout_cast(context,
                         self.make_msg('network_delete',
                                       network_id=network_id),
                         topic=self.topic_network_delete)

    def port_update(self, context, port, network_type, segmentation_id,
                    physical_network):
        self.fanout_cast(context,
                         self.make_msg('port_update',
                                       port=port,
                                       network_type=network_type,
                                       segmentation_id=segmentation_id,
                                       physical_network=physical_network),
                         topic=self.topic_port_update)

                                                            
                                                                 
class OmniSwitchNetworkPluginV2(db_base_plugin_v2.NeutronDbPluginV2,
                         external_net_db.External_net_db_mixin,
                         extraroute_db.ExtraRoute_db_mixin,
                         l3_gwmode_db.L3_NAT_db_mixin,
                         sg_db_rpc.SecurityGroupServerRpcMixin,
                         l3_agentschedulers_db.L3AgentSchedulerDbMixin,
                         agentschedulers_db.DhcpAgentSchedulerDbMixin,
                         portbindings_db.PortBindingMixin,
                         extradhcpopt_db.ExtraDhcpOptMixin,
                         addr_pair_db.AllowedAddressPairsMixin):

    """ 
    Name:        OmniSwitchNetworkPluginV2 
    Description: OpenStack Neutron core plugin for network comprises of OmniSwitch and 
                 OpenVSwitch devices. 

    Details:     It acts as core plugin for Neutron server and dispatches the API2.0 calls
                 to each of the device plugins such as OVSNeutronPluginV2 and 
                 OmniSwitchDevicePluginV2. The individual device plugins communicate with 
                 the devices that they support respectively, using their configuration and
                 device specific interfacing mechanism.
    """

    # This attribute specifies whether the plugin supports or not
    # bulk operations. Name mangling is used in order to ensure it
    # is qualified by class
    __native_bulk_support = True
    __native_pagination_support = True
    __native_sorting_support = True    
    _supported_extension_aliases = ["provider", "external-net", "router",
                                    "ext-gw-mode", "binding", "quotas", 
                                    "security-group", "agent", "extraroute",
                                    "l3_agent_scheduler",
                                    "dhcp_agent_scheduler",
                                    "extra_dhcp_opt",
                                    "allowed-address-pairs"]

    @property
    def supported_extension_aliases(self):
        if not hasattr(self, '_aliases'):
            aliases = self._supported_extension_aliases[:]
            sg_rpc.disable_security_group_extension_if_noop_driver(aliases)
            self._aliases = aliases
        return self._aliases

    ovs_plugin = ''
    omni_plugin = ''
    ovs_plugin_obj = None
    omni_plugin_obj = None
    omni_db_obj = None

    network_vlan_ranges = {}

    _semInUse = 0

    def __init__(self):
        self._load_config()
        self._load_device_plugins()
        self.setup_rpc()

        self.network_scheduler = importutils.import_object( cfg.CONF.network_scheduler_driver)
        self.router_scheduler = importutils.import_object(cfg.CONF.router_scheduler_driver) 

    def _load_config(self, conf_file=None):
        self.configFile = conf_file

        #cfg.CONF.register_opts(database_opts, "DATABASE")
        cfg.CONF.register_opts(plugin_opts, "PLUGIN")

        self.ovs_plugin = cfg.CONF.PLUGIN.ovs_plugin.strip()
        self.omni_plugin = cfg.CONF.PLUGIN.omni_plugin.strip()
        #LOG.info("VAD: plugins: %s, %s", self.ovs_plugin, self.omni_plugin)

    def _load_device_plugins(self):
        # Load OVS plug-in, if configured, and use its database parameters
        if len(self.ovs_plugin) != 0:
            # if ovs plug-in is configured, use ovs plug-in's database parameters
            self.ovs_plugin_obj = importutils.import_object(self.ovs_plugin)
            self.omni_db_obj = importutils.import_object(omni_const.OMNI_DB_CLASS)
            self.omni_db_obj.initialize(None, None, None, omni_const.OVS_TABLES)

        else:
            # if ovs plug-in is not configured, use omni plug-in's database parameters
            self.omni_db_obj = importutils.import_object(omni_const.OMNI_DB_CLASS)
            self.omni_db_obj.initialize(None, None, None, omni_const.OMNI_TABLES)
            self._parse_network_vlan_ranges()
            self.omni_db_obj.sync_vlan_allocations(self.network_vlan_ranges)

            config.register_agent_state_opts_helper(cfg.CONF)
            config.register_root_helper(cfg.CONF)
            #cfg.CONF.register_opts(scheduler.AGENTS_SCHEDULER_OPTS) # for havana

        # Load Omni device plug-in
        if len(self.omni_plugin) != 0:
            self.omni_plugin_obj = importutils.import_object(self.omni_plugin)
            self.omni_plugin_obj.initialize(self.omni_db_obj)
        else:
            LOG.info("Omni Device plug-in is not specified in the config!!!")
            return

        LOG.info("Device plug-ins loaded!")

    def setup_rpc(self):
        # RPC support
        self.service_topics = {svc_constants.CORE: topics.PLUGIN,
                               svc_constants.L3_ROUTER_NAT: topics.L3PLUGIN}
        self.conn = rpc.create_connection(new=True)
        self.notifier = AgentNotifierApi(topics.AGENT)
        self.agent_notifiers[q_const.AGENT_TYPE_DHCP] = (
            dhcp_rpc_agent_api.DhcpAgentNotifyAPI()
        )
        self.agent_notifiers[q_const.AGENT_TYPE_L3] = (
            l3_rpc_agent_api.L3AgentNotify
        )
        self.callbacks = OmniRpcCallbacks(self.notifier, self.omni_db_obj)
        self.dispatcher = self.callbacks.create_rpc_dispatcher()
        for svc_topic in self.service_topics.values():
            self.conn.create_consumer(svc_topic, self.dispatcher, fanout=False)
        # Consume from all consumers in a thread
        self.conn.consume_in_thread()

    def _invoke_device_plugin_api(self, function_name, args):
        if(self.ovs_plugin_obj):
            return getattr(self.ovs_plugin_obj, function_name)(*args)
        else:
            return getattr(super(OmniSwitchNetworkPluginV2, self), function_name)(*args)
        
    def _func_name(self, offset=0):
        return inspect.stack()[1 + offset][3]

    def _parse_network_vlan_ranges(self):
        self.network_vlan_ranges = {}
        for entry in cfg.CONF.PLUGIN.network_vlan_ranges:
            entry = entry.strip()
            if ':' in entry:
                try:
                    physical_network, vlan_min, vlan_max = entry.split(':')
                    self._add_network_vlan_range(physical_network.strip(),
                                                 int(vlan_min),
                                                 int(vlan_max))
                except ValueError as ex:
                    LOG.error("Invalid network VLAN range: '%s' - %s. ", entry, ex)
                    sys.exit(1)
            else:
                self._add_network(entry)
        LOG.info("Network VLAN ranges = %s", self.network_vlan_ranges)

    def _add_network_vlan_range(self, physical_network, vlan_min, vlan_max):
        self._add_network(physical_network)
        self.network_vlan_ranges[physical_network].append((vlan_min, vlan_max))

    def _add_network(self, physical_network):
        if physical_network not in self.network_vlan_ranges:
            self.network_vlan_ranges[physical_network] = []

    def _extend_network_dict_provider(self, context, network):
        binding = self.omni_db_obj.get_network_binding(context.session, network['id'])
        network[provider.NETWORK_TYPE] = binding.network_type
        network[provider.PHYSICAL_NETWORK] = binding.physical_network
        network[provider.SEGMENTATION_ID] = binding.segmentation_id

    def _semTake(self):
        while(self._semInUse == 1):
            continue
        self._semInUse = 1

    def _semGive(self):
        self._semInUse = 0


    """ ************** Neutron Core API 2.0 ************** """

    def create_network_bulk(self, context, networks):
        return self._invoke_device_plugin_api(self._func_name(), [context, networks])

    def create_network(self, context, network):
        if(self.ovs_plugin_obj):
            opennet = self.ovs_plugin_obj.create_network(context, network)
        else:
            session = context.session
            with session.begin(subtransactions=True):
                (physical_network, segmentation_id) = self.omni_db_obj.reserve_vlan(session)
                opennet = super(OmniSwitchNetworkPluginV2, self).create_network(context, network)
                self.omni_db_obj.add_network_binding(session, opennet['id'], 'vlan', physical_network, segmentation_id)
                self._process_l3_create(context, opennet, network['network'])
                self._extend_network_dict_provider(context, opennet)
                self._extend_network_dict_l3(context, opennet)

        network.setdefault('id',opennet['id']) 
        ret = self.omni_plugin_obj.create_network(context, network)
        if(ret):
            return opennet
        else:
            # some error while creating network in the omni switches, so roll back the create operation and return fail
            LOG.info("create_network failed in omniswithces! %s", network)
            self._invoke_device_plugin_api('delete_network', [context, opennet['id']])
            return None

    def update_network(self, context, id, network):
        return self._invoke_device_plugin_api(self._func_name(), [context, id, network])

    def delete_network(self, context, id):
        ret = self.omni_plugin_obj.delete_network(context, id)
        if not ret:
           LOG.info("delete_network failed in omniswithces! %s", id)

        if(self.ovs_plugin_obj):
            return self.ovs_plugin_obj.delete_network(context, id)
        else:
            session = context.session
            with session.begin(subtransactions=True):
                binding = self.omni_db_obj.get_network_binding(session, id)
                super(OmniSwitchNetworkPluginV2, self).delete_network(context, id)
                self.omni_db_obj.release_vlan(session, binding.physical_network,
                                           binding.segmentation_id,
                                           self.network_vlan_ranges)
        return True

    def get_network(self, context, id, fields=None):
        return self._invoke_device_plugin_api(self._func_name(), [context, id, fields])

    def get_networks(self, context, filters=None, fields=None):
        return self._invoke_device_plugin_api(self._func_name(), [context, filters, fields])

    def get_networks_count(self, context, filters=None):
        return self._invoke_device_plugin_api(self._func_name(), [context, filters])

    def create_subnet_bulk(self, context, subnets):
        return self._invoke_device_plugin_api(self._func_name(), [context, subnets])

    def create_subnet(self, context, subnet):
        return self._invoke_device_plugin_api(self._func_name(), [context, subnet])

    def update_subnet(self, context, id, subnet):
        return self._invoke_device_plugin_api(self._func_name(), [context, id, subnet])

    def delete_subnet(self, context, id):
        ret = self.omni_plugin_obj.delete_subnet(context, id)
        if not ret:
           LOG.info("delete_subnet failed in omniswithces! %s", id)

        if(self.ovs_plugin_obj):
            return self.ovs_plugin_obj.delete_subnet(context, id)
        return True

    def get_subnet(self, context, id, fields=None):
        return self._invoke_device_plugin_api(self._func_name(), [context, id, fields])

    def get_subnets(self, context, filters=None, fields=None):
        return self._invoke_device_plugin_api(self._func_name(), [context, filters, fields])

    def get_subnets_count(self, context, filters=None):
        return self._invoke_device_plugin_api(self._func_name(), [context, filters])

    def create_port_bulk(self, context, ports):
        return self._invoke_device_plugin_api(self._func_name(), [context, ports])

    def create_port(self, context, port):
        openport = self._invoke_device_plugin_api(self._func_name(), [context, port])
        ret = self.omni_plugin_obj.create_port(context, openport)
        if ret:
            return openport
        else:
            LOG.info("create_port failed in omniswitches! %s", port)
            return None

    def update_port(self, context, id, port):
        updated_port = self._invoke_device_plugin_api(self._func_name(), [context, id, port])
        binding = self.omni_db_obj.get_network_binding(None,
                                                    updated_port['network_id'])
        return updated_port


    def delete_port(self, context, id, l3_port_check=True):
        if l3_port_check:
            self.prevent_l3_port_deletion(context, id)

        ret = self.omni_plugin_obj.delete_port(context, id)
        if ret:
            return self._invoke_device_plugin_api(self._func_name(), [context, id, l3_port_check])
        else:
            LOG.info("delete_port failed in omniswitches! %s", id)
            return None

    def get_port(self, context, id, fields=None):
        return self._invoke_device_plugin_api(self._func_name(), [context, id, fields])

    def get_ports(self, context, filters=None, fields=None):
        return self._invoke_device_plugin_api(self._func_name(), [context, filters, fields])

    def get_ports_count(self, context, filters=None):
        return self._invoke_device_plugin_api(self._func_name(), [context, filters])



class OmniRpcCallbacks(dhcp_rpc_base.DhcpRpcCallbackMixin,
                      l3_rpc_base.L3RpcCallbackMixin,
                      sg_db_rpc.SecurityGroupServerRpcCallbackMixin):

    # history
    #   1.0 Initial version
    #   1.1 Support Security Group RPC

    RPC_API_VERSION = '1.1'

    def __init__(self, notifier, db_obj):
        self.notifier = notifier
        self.omni_db_obj = db_obj

    def create_rpc_dispatcher(self):
        '''Get the rpc dispatcher for this manager.

        If a manager would like to set an rpc API version, or support more than
        one class as the target of rpc messages, override this method.
        '''
        return q_rpc.PluginRpcDispatcher([self,
                                          agents_db.AgentExtRpcCallback()])
    @classmethod
    def get_port_from_device(cls, device):
        port = omni_dbutils.get_port_from_device(device)
        if port:
            port['device'] = device
        return port

    def get_device_details(self, rpc_context, **kwargs):
        """Agent requests device details"""
        agent_id = kwargs.get('agent_id')
        device = kwargs.get('device')
        LOG.debug(_("Device %(device)s details requested from %(agent_id)s"),
                  locals())
        port = omni_dbutils.get_port(device)
        if port:
            binding = self.omni_db_obj.get_network_binding(None, port['network_id'])
            entry = {'device': device,
                     'network_id': port['network_id'],
                     'port_id': port['id'],
                     'admin_state_up': port['admin_state_up'],
                     'network_type': binding.network_type,
                     'segmentation_id': binding.segmentation_id,
                     'physical_network': binding.physical_network}
            new_status = (q_const.PORT_STATUS_ACTIVE if port['admin_state_up']
                          else q_const.PORT_STATUS_DOWN)
            if port['status'] != new_status:
                omni_dbutils.set_port_status(port['id'], new_status)
        else:
            entry = {'device': device}
            LOG.debug(_("%s can not be found in database"), device)
        return entry

    def update_device_down(self, rpc_context, **kwargs):
        """Device no longer exists on agent"""
        # (TODO) garyk - live migration and port status
        agent_id = kwargs.get('agent_id')
        device = kwargs.get('device')
        LOG.debug(_("Device %(device)s no longer exists on %(agent_id)s"),
                  locals())
        port = omni_dbutils.get_port(device)
        if port:
            entry = {'device': device,
                     'exists': True}
            if port['status'] != q_const.PORT_STATUS_DOWN:
                # Set port status to DOWN
                omni_dbutils.set_port_status(port['id'], q_const.PORT_STATUS_DOWN)
        else:
            entry = {'device': device,
                     'exists': False}
            LOG.debug(_("%s can not be found in database"), device)
        return entry

    def update_device_up(self, rpc_context, **kwargs):
        """Device is up on agent"""
        agent_id = kwargs.get('agent_id')
        device = kwargs.get('device')
        LOG.debug(_("Device %(device)s up on %(agent_id)s"),
                  locals())
        port = omni_dbutils.get_port(device)
        if port:
            if port['status'] != q_const.PORT_STATUS_ACTIVE:
                omni_dbutils.set_port_status(port['id'],
                                          q_const.PORT_STATUS_ACTIVE)
        else:
            LOG.debug(_("%s can not be found in database"), device)



class AgentNotifierApi(proxy.RpcProxy,
                       sg_rpc.SecurityGroupAgentRpcApiMixin):
    '''Agent side of the OmniSwitch rpc API.

    API version history:
        1.0 - Initial version.

    '''

    BASE_RPC_API_VERSION = '1.0'

    def __init__(self, topic):
        super(AgentNotifierApi, self).__init__(
            topic=topic, default_version=self.BASE_RPC_API_VERSION)
        self.topic_network_delete = topics.get_topic_name(topic,
                                                          topics.NETWORK,
                                                          topics.DELETE)
        self.topic_port_update = topics.get_topic_name(topic,
                                                       topics.PORT,
                                                       topics.UPDATE)

    def network_delete(self, context, network_id):
        self.fanout_cast(context,
                         self.make_msg('network_delete',
                                       network_id=network_id),
                         topic=self.topic_network_delete)

    def port_update(self, context, port, network_type, segmentation_id,
                    physical_network):
        self.fanout_cast(context,
                         self.make_msg('port_update',
                                       port=port,
                                       network_type=network_type,
                                       segmentation_id=segmentation_id,
                                       physical_network=physical_network),
                         topic=self.topic_port_update)


