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
# $File: omniswitch_constants.py$

# $Build: OONP_H_R01_6$

# $Date: 05/06/2014 12:10:39$

# $Author: vapoonat$

#
#


### Constants used in OmniSwitch Neutron Network plug-in ###


# Used by Network Plug-in #
OMNI_DB_CLASS = 'neutron.plugins.omniswitch.omniswitch_db_v2.OmniDB'
OMNI_TABLES = 1
OVS_TABLES = 2

# Used by Device Plug-in #
OMNI_CFG_DEV_IP = 0
OMNI_CFG_DEV_TYPE = 1
OMNI_CFG_DEV_LOGIN = 2
OMNI_CFG_DEV_PASSWORD = 3
OMNI_CFG_DEV_PROMPT = 4
OMNI_CFG_DEV_EDGE2COMPUTE_IF = 5
OMNI_CFG_DEV_EDGE2CORE_IF = 6

OMNI_CFG_DEV_CORE_IF = 5
OMNI_CFG_DHCP_SERVER_IF = 5

OMNISWITCH_6XX = 1
OMNISWITCH_7XX = 2
OMNISWITCH_8XX = 3

OMNISWITCH_OS6900 = "OS6900"
OMNISWITCH_OS10K = "OS10K"
OMNISWITCH_OS6850E = "OS6850E"
OMNISWITCH_OS6855 = "OS6855"
OMNISWITCH_OS6450 = "OS6450"
OMNISWITCH_OS9000 = "OS9000"
OMNISWITCH_OS6860 = "OS6860"


OMNI_CFG_CORE_MVRP = "MVRP"
OMNI_CFG_CORE_VPA = "VPA"
OMNI_CFG_CORE_SPB = "SPB"

OMNI_CFG_HOST_CLASS_MAC = "MAC_ADDRESS"
OMNI_CFG_HOST_CLASS_VTAG = "VLAN_TAG"

OMNI_CFG_SWITCH_ACCESS_REST = "REST"
OMNI_CFG_SWITCH_ACCESS_TELNET = "TELNET"

OMNI_CFG_CREATE = 1
OMNI_CFG_DELETE = 0

OMNI_CFG_ENABLE = 1
OMNI_CFG_DISABLE = 0

# Used by Telnet/CLI driver
OMNI_CLI_PROMPT = "->"
OMNI_CLI_PROMPT_TIMEOUT = 1
OMNI_CLI_SMALL_TIMEOUT = 2
OMNI_CLI_MEDIUM_TIMEOUT = 5
OMNI_CLI_LONG_TIMEOUT = 10

# Used by RESTful driver #

