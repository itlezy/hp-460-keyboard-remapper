"""Fixed auxiliary-protocol enable/read/reset test over the HP vendor GATT service.

Changes a temporary protocol state. No transfer start/data, reset of Windows or
keyboard, arbitrary address, native-mode flag, Fn Lock or stored program write.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from experiments.ble_vendor_read import PROBE, run_source


ACTIONS = r'''
   if($bleChar.Uuid.ToString() -eq '0000ff01-0000-1000-8000-00805f9b34fb') {
    function Read-Auxiliary($characteristic) {
     $read=Await-Ble ($characteristic.ReadValueAsync([Windows.Devices.Bluetooth.BluetoothCacheMode]::Uncached)) ([Windows.Devices.Bluetooth.GenericAttributeProfile.GattReadResult, Windows.Devices.Bluetooth, ContentType=WindowsRuntime])
     if($read.Status.ToString() -ne 'Success'){throw [System.InvalidOperationException]::new('Read failed')}
     [byte[]]$bytes=[HpBleBuffer]::Copy($read.Value)
     return ([BitConverter]::ToString($bytes)).Replace('-','')
    }
    function Write-Auxiliary($characteristic,[byte]$command) {
     $buffer=[System.Runtime.InteropServices.WindowsRuntime.WindowsRuntimeBufferExtensions]::AsBuffer([byte[]]@($command))
     $write=Await-Ble ($characteristic.WriteValueWithResultAsync($buffer,[Windows.Devices.Bluetooth.GenericAttributeProfile.GattWriteOption]::WriteWithResponse)) ([Windows.Devices.Bluetooth.GenericAttributeProfile.GattWriteResult, Windows.Devices.Bluetooth, ContentType=WindowsRuntime])
     return $write.Status.ToString()
    }
    $bleStage='auxiliary_precondition'
    $bleRecord.before_hex=Read-Auxiliary $bleChar
    if(__RESET_ONLY__ -or $bleRecord.before_hex -match '^0+$') {
     try {
      if(-not __RESET_ONLY__) {
       $bleRecord.enable_attempted=$true
       $bleStage='auxiliary_enable'
       $bleRecord.enable_status=Write-Auxiliary $bleChar 0x10
       if($bleRecord.enable_status -eq 'Success') {
        $bleStage='auxiliary_read_enabled'
        $bleRecord.enabled_hex=Read-Auxiliary $bleChar
        $bleRecord.expected_enable_reply=$bleRecord.enabled_hex.StartsWith('0E021000')
        if(__QUERY_INFO__ -and $bleRecord.expected_enable_reply) {
         $bleRecord.queries=@()
         foreach($query in @(0x23,0x2C)) {
          $bleStage='auxiliary_information_query'
          $queryStatus=Write-Auxiliary $bleChar ([byte]$query)
          $queryReply=Read-Auxiliary $bleChar
          $bleRecord.queries+=,@{command=$query;status=$queryStatus;reply_hex=$queryReply}
         }
        }
       }
      }
     } finally {
      try {
       $bleStage='auxiliary_reset'
       $bleRecord.reset_status=Write-Auxiliary $bleChar 0x28
       $bleRecord.reset_hex=Read-Auxiliary $bleChar
       $bleRecord.reset_confirmed=($bleRecord.reset_status -eq 'Success' -and $bleRecord.reset_hex -match '^0+$')
      } catch {
       $bleRecord.reset_status='failed'
       $bleRecord.reset_error_type=$_.Exception.GetType().Name
       $bleRecord.reset_confirmed=$false
      }
     }
    } else {$bleRecord.handshake_status='skipped_nonempty_initial_reply'}
   }
'''


def run(reset_only=False, query_info=False):
    actions = ACTIONS.replace("__RESET_ONLY__", "$true" if reset_only else "$false").replace("__QUERY_INFO__", "$true" if query_info else "$false")
    return run_source(PROBE.replace("__READ_VALUES__", "$false").replace("__AUXILIARY_ACTIONS__", actions))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--reset-only", action="store_true", help="send only the auxiliary protocol bookkeeping reset")
    parser.add_argument("--query-info", action="store_true", help="also query fixed device information (23) and auxiliary mode (2C)")
    parser.add_argument("--output", type=Path, help="exclusive-create private raw report")
    args = parser.parse_args()
    if os.name != "nt":
        parser.error("Requires Windows")
    if args.reset_only and args.query_info:
        parser.error("Choose either reset-only or information queries")
    if args.output and args.output.exists():
        parser.error("Output already exists; refusing to overwrite")
    report = run(args.reset_only, args.query_info)
    target = next((c for c in report.get("characteristics", [])
                   if c.get("uuid") == "0000ff01-0000-1000-8000-00805f9b34fb"), {})
    uncertain_process = report.get("status") in ("process_failed", "process_timeout")
    if not args.reset_only and (uncertain_process or (target.get("enable_attempted") and not target.get("reset_confirmed"))):
        report["recovery"] = run(True)
    if args.output:
        with args.output.open("x", encoding="utf-8") as stream:
            json.dump(report, stream, indent=2)
            stream.write("\n")
    public = {"status": report.get("status"), "enable_status": target.get("enable_status"),
              "expected_enable_reply": target.get("expected_enable_reply"),
              "reset_status": target.get("reset_status"), "reset_confirmed": target.get("reset_confirmed")}
    queries = []
    for query in target.get("queries", []):
        raw = bytes.fromhex(query["reply_hex"])
        valid = len(raw) >= 4 and raw[0] == 0x0E and raw[1] + 2 == len(raw) and raw[2] == query["command"]
        queries.append({"command": f"{query['command']:02X}", "status": query["status"], "valid_reply": valid})
        if query["command"] == 0x2C and valid and len(raw) == 5 and raw[3] == 0:
            public["auxiliary_mode"] = raw[4]
    if queries:
        public["queries"] = queries
    if "recovery" in report:
        public["recovery"] = [{"reset_status": c.get("reset_status"), "reset_confirmed": c.get("reset_confirmed")}
                              for c in report["recovery"].get("characteristics", []) if "reset_status" in c]
    print(json.dumps(public, indent=2))
    if not target.get("reset_confirmed") or (not args.reset_only and not target.get("expected_enable_reply")) or any(q["status"] != "Success" or not q["valid_reply"] for q in queries):
        raise SystemExit(2)


if __name__ == "__main__":
    main()
