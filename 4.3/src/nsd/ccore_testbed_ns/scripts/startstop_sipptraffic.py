#!/usr/bin/env python3
import argparse
import logging
import os
import stat
import subprocess
import sys
import time
import yaml
import paramiko

'''
{config_agent: {name: RiftCA, type: riftca}, init_config: {7cceec3f-b29d-42e2-ab7c-0f4e44bcbfd0: {},
    ad92b819-d459-4c93-826d-b1d850d44b88: {}, c7a93b87-b419-4f50-aa73-03085c863823: {},
    cad80398-106b-4212-8589-682804010a51: {}, e0eeddbe-4ce3-42b9-befc-afb59bf0d8b6: {},
    e6423d40-9388-4781-9c9e-0791307174c9: {}}, rpc_ip: {name: SIPP Traffic Client,
    nsr_id_ref: 3f26cf94-3a8d-44ba-8cb0-8c7badaa0a50, parameter: [{name: Trigger,
        value: start}], triggered_by: ns_primitive, user_defined_script: startstop_sipptraffic.py},
  unit_names: {7cceec3f-b29d-42e2-ab7c-0f4e44bcbfd0: NS1__homesteadprov_vnfd__2, ad92b819-d459-4c93-826d-b1d850d44b88: null,
    c7a93b87-b419-4f50-aa73-03085c863823: NS1__sprout_vnfd__6, cad80398-106b-4212-8589-682804010a51: NS1__homesteadprov_vnfd__1,
    e0eeddbe-4ce3-42b9-befc-afb59bf0d8b6: NS1__dnsserver_vnfd__5, e6423d40-9388-4781-9c9e-0791307174c9: NS1__homesteadprov_vnfd__3},
  vnfr_data_map: {1: {connection_point: [{ip_address: 14.0.0.2, name: homesteadprov_vnfd/sigport}],
      mgmt_interface: {ip_address: 10.66.217.145, port: 0}, vdur: [{id: 6c337e45-04ff-4c05-a3b8-a65a6685e518,
          management_ip: 10.66.217.145, name: iovdu_0, vm_management_ip: 10.0.217.197}]},
    2: {connection_point: [{ip_address: 14.0.0.7, name: homesteadprov_vnfd/sigport}],
      mgmt_interface: {ip_address: 10.66.217.150, port: 0}, vdur: [{id: 3504ad2c-8d7b-40aa-ac54-0bb32c527e0b,
          management_ip: 10.66.217.150, name: iovdu_0, vm_management_ip: 10.0.217.202}]},
    3: {connection_point: [{ip_address: 14.0.0.6, name: homesteadprov_vnfd/sigport}],
      mgmt_interface: {ip_address: 10.66.217.149, port: 0}, vdur: [{id: 2426c556-363d-4541-8c95-9ad1251d2e1d,
          management_ip: 10.66.217.149, name: iovdu_0, vm_management_ip: 10.0.217.201}]},
    4: {connection_point: [{ip_address: 14.0.0.3, name: sipp_vnfd/cp0}], mgmt_interface: {
        ip_address: 10.66.217.146, port: 2022}, vdur: [{id: d6492bbb-91a0-4c97-a977-b45edda3513d,
          management_ip: 10.66.217.146, name: iovdu, vm_management_ip: 10.0.217.198}]},
    5: {connection_point: [{ip_address: 14.0.0.5, name: dnsserver_vnfd/sigport}],
      mgmt_interface: {ip_address: 10.66.217.148, port: 0}, vdur: [{id: ad30d46f-31c6-4d54-8bd6-789b6db9c5a0,
          management_ip: 10.66.217.148, name: iovdu_0, vm_management_ip: 10.0.217.200}]},
    6: {connection_point: [{ip_address: 14.0.0.4, name: sprout_vnfd/sigport}], mgmt_interface: {
        ip_address: 10.66.217.147, port: 0}, vdur: [{id: 148b2920-520c-48a2-9492-9c4e19f41c54,
          management_ip: 10.66.217.147, name: iovdu_0, vm_management_ip: 10.0.217.199}]}},
  vnfr_index_map: {1: cad80398-106b-4212-8589-682804010a51, 2: 7cceec3f-b29d-42e2-ab7c-0f4e44bcbfd0,
    3: e6423d40-9388-4781-9c9e-0791307174c9, 4: ad92b819-d459-4c93-826d-b1d850d44b88,
    5: e0eeddbe-4ce3-42b9-befc-afb59bf0d8b6, 6: c7a93b87-b419-4f50-aa73-03085c863823}}
'''
class ConfigurationError(Exception):
    pass

def copy_file_ssh_sftp(logger, server, username, remote_dir, remote_file, local_file):
    sshclient = paramiko.SSHClient()
    sshclient.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    sshclient.load_system_host_keys(filename="/dev/null")
    sshclient.connect(server, username=username, password="fedora")
    sftpclient = sshclient.open_sftp()
    sftpclient.put(local_file, remote_dir + '/' + remote_file)
    sshclient.close()


def get_vnf_file(logger, file_name, d_name, d_id, d_type):
    logger.debug("Obtaining local file %s", file_name)
    # Get the full path to the vnf file
    vnffile = ''
    # If vnf file name name starts with /, assume it is full path
    if file_name[0] == '/':
        # The vnf file name has full path, use as is
        vnffile = file_name
    else:
        vnffile = os.path.join(os.environ['RIFT_ARTIFACTS'],
                                  'launchpad/packages',
                                  d_type,
                                  d_id,
                                  d_name,
                                  'scripts',
                                  file_name)
        logger.debug("Checking for vnf file name at %s", vnffile)
        if not os.path.exists(vnffile):
            logger.debug("Did not find file %s", vnffile)
            vnffile = os.path.join(os.environ['RIFT_INSTALL'],
                                      'usr/bin',
                                      file_name)
    return vnffile

def start_sipp_traffic(logger, run_dir, vnf_mgmt_ip, sipp_sig_ip, trigger, calls_per_sec):
    logger.debug("Starting SIPP scenario ")

    sh_file = "{}/start_sipp-{}.sh".format(run_dir, time.strftime("%Y%m%d%H%M%S"))
    logger.debug("Creating SIPP file %s", sh_file)
    with open(sh_file, "w") as f:
        f.write(r'''#!/usr/bin/expect -f
set login "fedora"
set pw "fedora"
set success 0
spawn ssh -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null $login@{vnf_mgmt_ip}
set spid $spawn_id
set timeout 60

if {{[llength $argv] != 1}} {{
  send_user "Usage: ./startstop_sipptraffic.sh <trigger> "
  exit 1
}}

set trigger [lindex $argv 0]
set sipp_local_port 5060

expect -i $spid \
                  "*?assword:"      {{
                                exp_send -i $spid "$pw\r"
                                if {{ $success == 0 }} {{
                                        incr success -1
                                        exp_continue
                                }}
                }} "]$ "  {{
                        set success 1
                }} "yes/no"      {{
                        exp_send -i $spid "yes\r"
                        exp_continue
                }} timeout       {{
                        set success -1
                }}

send "export TERM=xterm\r"
expect "]$ "

# Cleanup existing ones and restart sipp
send "pkill sipp-master\r"
expect "]$ "
send "rm -f /tmp/sipp_stats*.txt\r"
expect "]$ "

if {{ $trigger eq "start" }} {{
   send "dig -t A sprout.test.com +noall +answer\r"
   expect "]$ "
   set dig_output  $expect_out(buffer)
   set sproutip_list [regexp -inline -all {{\d+\.\d+\.\d+\.\d+}} $dig_output]

   set call_rate {calls_per_sec}
   set num_sprouts [llength $sproutip_list]
   puts "Regex list for sprout ips: $sproutip_list"
   set per_sipp_call_rate [expr {{ $call_rate/$num_sprouts }}]
 

   set filectr 1
   foreach sproutip $sproutip_list {{
      send "./sipp-master -sf reg_auth_dereg.xml -inf data1.csv -i {sipp_sig_ip} -p $sipp_local_port -key registrar test.com -l 0 -r $per_sipp_call_rate -t t1 $sproutip:5052 -trace_stat -stf /tmp/sipp_stats$filectr.txt -bg -fd 20\r"
      expect "]$ "
      incr sipp_local_port
      incr filectr
   }}
}}
exp_close -i $spid
'''.format(vnf_mgmt_ip=vnf_mgmt_ip, sipp_sig_ip=sipp_sig_ip, calls_per_sec=calls_per_sec))

    os.chmod(sh_file, stat.S_IRWXU)
    cmd = "{sh_file} {trigger}".format(sh_file=sh_file, trigger=trigger)
    logger.debug("Executing shell cmd : %s", cmd)
    rc = subprocess.call(cmd, shell=True)
    if rc != 0:
        raise ConfigurationError("SIPP traffic start failed: {}".format(rc))




def main(argv=sys.argv[1:]):
    try:
        parser = argparse.ArgumentParser()
        parser.add_argument("yaml_cfg_file", type=argparse.FileType('r'))
        parser.add_argument("--quiet", "-q", dest="verbose", action="store_false")
        args = parser.parse_args()

        run_dir = os.path.join(os.environ['RIFT_INSTALL'], "var/run/rift")
        if not os.path.exists(run_dir):
            os.makedirs(run_dir)
        log_file = "{}/sipp_startstop-{}.log".format(run_dir, time.strftime("%Y%m%d%H%M%S"))
        logging.basicConfig(filename=log_file, level=logging.DEBUG)
        logger = logging.getLogger()

        ch = logging.StreamHandler()
        if args.verbose:
            ch.setLevel(logging.DEBUG)
        else:
            ch.setLevel(logging.INFO)

        # create formatter and add it to the handlers
        formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
        ch.setFormatter(formatter)
        logger.addHandler(ch)

    except Exception as e:
        print("Got exception:{}".format(e))
        raise

    try:
        yaml_str = args.yaml_cfg_file.read()
        logger.debug("Input YAML file: %s", yaml_str)
        yaml_cfg = yaml.load(yaml_str)
        logger.debug("Input YAML cfg: %s", yaml_cfg)

        # Check if this is post scale out trigger
        def find_vnfr(vnfr_dict, mbr_vnf_index):
            try:
               return vnfr_dict[mbr_vnf_index]
            except KeyError:
               logger.warn("Could not find vnfr for mbr vnf index : %d", mbr_vnf_index)

        def find_cp_ip(vnfr, cp_name):
            for cp in vnfr['connection_point']:
               logger.debug("Connection point: %s", format(cp))
               if cp_name in cp['name']:
                  return cp['ip_address']

            raise ValueError("Could not find vnfd %s connection point %s", cp_name)

        # This is temporary. All this data should come from VLR
        def get_ipv4_subnet(vnfr, cp_name):
            for cp in vnfr['connection_point']:
               logger.debug("Connection point: %s", format(cp))
               if cp_name in cp['name']:
                  nw = cp['ip_address'].split(".")
                  subnet = nw[0]+"."+nw[1]+"."+nw[2]+".0/24"
                  return subnet

            raise ValueError("Could not find vnfd %s connection point %s", cp_name)

        def find_vnfr_mgmt_ip(vnfr):
            return vnfr['mgmt_interface']['ip_address']

        def find_vdur_mgmt_ip(vnfr):
            return vnfr['vdur'][0]['vm_management_ip']

        def find_param_value(param_list, input_param):
            for item in param_list:
               logger.debug("Parameter: %s", format(item))
               if item['name'] == input_param:
                  return item['value']

        trigger = find_param_value(yaml_cfg['rpc_ip']['parameter'], 'Trigger')
        call_rate = find_param_value(yaml_cfg['rpc_ip']['parameter'], 'Target call rate')

        sipp_info = dict()
        sipp_vnfr = find_vnfr(yaml_cfg['vnfr_data_map'], 4)
        sipp_info['floating_mgmt_ip'] = find_vnfr_mgmt_ip(sipp_vnfr)
        sipp_info['local_mgmt_ip'] = find_vdur_mgmt_ip(sipp_vnfr)
        sipp_info['sig_ip'] = find_cp_ip(sipp_vnfr, 'sipp_vnfd/cp0')

        logger.debug("Configuring SIPP VNF..")
        start_sipp_traffic(logger, run_dir, sipp_info['floating_mgmt_ip'], sipp_info['sig_ip'], trigger, call_rate)

    except Exception as e:
        logger.exception(e)
        raise

if __name__ == "__main__":
    main()
