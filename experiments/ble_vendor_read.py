"""Inspect the paired HP 460 vendor GATT service through native Windows APIs.

Python orchestrates Windows PowerShell's built-in WinRT projection. No package
installation, pairing change, characteristic write or device restart. Optional
raw read values belong in a private backup, not a public capture.
"""

from __future__ import annotations

import argparse
import base64
import json
import os
import subprocess
from pathlib import Path


PROBE = r'''
$ErrorActionPreference='Stop'; $ProgressPreference='SilentlyContinue'
$bleDevice=$null; $bleServices=@(); $bleStage='metadata'; $bleRecords=@()
try {
 Add-Type -AssemblyName System.Runtime.WindowsRuntime
 Add-Type -TypeDefinition @'
using System;
using System.Runtime.InteropServices;
[ComImport, Guid("905A0FEF-BC53-11DF-8C49-001E4FC686DA"), InterfaceType(ComInterfaceType.InterfaceIsIUnknown)]
interface IHpBufferByteAccess { [PreserveSig] int Buffer(out IntPtr pointer); }
[ComImport, Guid("905A0FE0-BC53-11DF-8C49-001E4FC686DA"), InterfaceType(ComInterfaceType.InterfaceIsIInspectable)]
interface IHpBuffer {
 [PreserveSig] int get_Capacity(out uint capacity);
 [PreserveSig] int get_Length(out uint length);
 [PreserveSig] int put_Length(uint length);
}
public static class HpBleBuffer {
 public static byte[] Copy(object buffer) {
  uint length;
  Marshal.ThrowExceptionForHR(((IHpBuffer)buffer).get_Length(out length));
  if (length > 512) throw new ArgumentOutOfRangeException("length");
  var result = new byte[length];
  if (length != 0) {
   IntPtr pointer;
   Marshal.ThrowExceptionForHR(((IHpBufferByteAccess)buffer).Buffer(out pointer));
   Marshal.Copy(pointer, result, 0, (int)length);
  }
  return result;
 }
}
'@
 $null=[Windows.Devices.Bluetooth.BluetoothLEDevice, Windows.Devices.Bluetooth, ContentType=WindowsRuntime]
 $null=[Windows.Devices.Bluetooth.BluetoothCacheMode, Windows.Devices.Bluetooth, ContentType=WindowsRuntime]
 $null=[Windows.Devices.Bluetooth.BluetoothAddressType, Windows.Devices.Bluetooth, ContentType=WindowsRuntime]
 $bleAsTask=[System.WindowsRuntimeSystemExtensions].GetMethods() | Where-Object {
  $_.Name -eq 'AsTask' -and $_.IsGenericMethod -and $_.GetParameters().Count -eq 2 -and
  $_.GetParameters()[0].ParameterType.Name -eq 'IAsyncOperation`1' -and
  $_.GetParameters()[1].ParameterType -eq [System.Threading.CancellationToken]
 } | Select-Object -First 1
 function Await-Ble($operation,$resultType) {
  $bleCancel=[System.Threading.CancellationTokenSource]::new()
  try {
   $bleCancel.CancelAfter(8000)
   $bleTask=$bleAsTask.MakeGenericMethod($resultType).Invoke($null,@($operation,$bleCancel.Token))
   if (-not $bleTask.Wait(10000)) {throw [System.TimeoutException]::new()}
   return $bleTask.Result
  } finally {$bleCancel.Dispose()}
 }
 $bleStage='paired_device'
 $hpDevice=@(Get-PnpDevice -PresentOnly | Where-Object FriendlyName -eq 'HP 460 Multi-Device Bluetooth Keyboard')
 if ($hpDevice.Count -ne 1) {
  @{status='requires_one_paired_device';matches=$hpDevice.Count}|ConvertTo-Json -Compress
  exit
 }
 $hpProps=Get-PnpDeviceProperty -InstanceId $hpDevice[0].InstanceId
 $bleAddress=[Convert]::ToUInt64((($hpProps|Where-Object KeyName -eq 'DEVPKEY_Bluetooth_DeviceAddress').Data -replace '[:-]',''),16)
 $bleAddressType=[Windows.Devices.Bluetooth.BluetoothAddressType][byte](($hpProps|Where-Object KeyName -eq 'DEVPKEY_BluetoothLE_AddressType').Data)
 $bleDevice=Await-Ble ([Windows.Devices.Bluetooth.BluetoothLEDevice]::FromBluetoothAddressAsync($bleAddress,$bleAddressType)) ([Windows.Devices.Bluetooth.BluetoothLEDevice])
 $bleStage='vendor_service'
 $bleResult=Await-Ble ($bleDevice.GetGattServicesForUuidAsync([guid]'0000ff00-0000-1000-8000-00805f9b34fb',[Windows.Devices.Bluetooth.BluetoothCacheMode]::Uncached)) ([Windows.Devices.Bluetooth.GenericAttributeProfile.GattDeviceServicesResult, Windows.Devices.Bluetooth, ContentType=WindowsRuntime])
 $bleServices=@($bleResult.Services)
 foreach($bleService in $bleServices) {
  $bleStage='characteristics'
  $bleChars=Await-Ble ($bleService.GetCharacteristicsAsync([Windows.Devices.Bluetooth.BluetoothCacheMode]::Uncached)) ([Windows.Devices.Bluetooth.GenericAttributeProfile.GattCharacteristicsResult, Windows.Devices.Bluetooth, ContentType=WindowsRuntime])
  if($bleChars.Status.ToString() -ne 'Success') {
   $bleRecords+=,@{status='characteristic_enumeration_failed';communication_status=$bleChars.Status.ToString()}
   continue
  }
  foreach($bleChar in $bleChars.Characteristics) {
   $bleRecord=@{uuid=$bleChar.Uuid.ToString();handle=$bleChar.AttributeHandle;properties=$bleChar.CharacteristicProperties.ToString()}
   $bleRecords+=,$bleRecord
__AUXILIARY_ACTIONS__
   if(__READ_VALUES__ -and $bleChar.Uuid.ToString() -in @('0000ff01-0000-1000-8000-00805f9b34fb','0000ff02-0000-1000-8000-00805f9b34fb')) {
    $bleStage='read_characteristic'
    $bleRead=Await-Ble ($bleChar.ReadValueAsync([Windows.Devices.Bluetooth.BluetoothCacheMode]::Uncached)) ([Windows.Devices.Bluetooth.GenericAttributeProfile.GattReadResult, Windows.Devices.Bluetooth, ContentType=WindowsRuntime])
    $bleRecord.read_status=$bleRead.Status.ToString()
    if($bleRead.Status.ToString() -eq 'Success') {
     $bleStage='read_buffer_bytes'
     [byte[]]$bleBytes=[HpBleBuffer]::Copy($bleRead.Value)
     $bleRecord.value_hex=([BitConverter]::ToString($bleBytes)).Replace('-','')
    }
   }
  }
 }
 @{status=$bleResult.Status.ToString();services=$bleServices.Count;characteristics=$bleRecords}|ConvertTo-Json -Depth 5 -Compress
} catch {
 @{status='probe_failed';stage=$bleStage;error_type=$_.Exception.GetType().Name;base_error=$_.Exception.GetBaseException().GetType().Name;characteristics=$bleRecords}|ConvertTo-Json -Depth 5 -Compress
} finally {
 foreach($bleService in $bleServices){if($null -ne $bleService){$bleService.Dispose()}}
 if($null -ne $bleDevice){$bleDevice.Dispose()}
}
'''


def run_source(source: str) -> dict:
    powershell = Path(os.environ["SystemRoot"]) / "System32/WindowsPowerShell/v1.0/powershell.exe"
    encoded = base64.b64encode(source.encode("utf-16-le")).decode("ascii")
    try:
        result = subprocess.run([str(powershell), "-NoProfile", "-NonInteractive", "-EncodedCommand", encoded],
            capture_output=True, text=True, timeout=55, creationflags=subprocess.CREATE_NO_WINDOW)
    except subprocess.TimeoutExpired:
        return {"status": "process_timeout"}
    if result.returncode or not result.stdout.strip():
        return {"status": "process_failed", "exit_code": result.returncode,
                "stdout": result.stdout, "stderr": result.stderr}
    return json.loads(result.stdout)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--read-values", action="store_true")
    parser.add_argument("--output", type=Path, help="exclusive-create private report; raw bytes omitted from stdout")
    args = parser.parse_args()
    if os.name != "nt":
        parser.error("Requires Windows")
    if args.output and args.output.exists():
        parser.error("Output already exists; refusing to overwrite")
    source = PROBE.replace("__READ_VALUES__", "$true" if args.read_values else "$false").replace("__AUXILIARY_ACTIONS__", "")
    report = run_source(source)
    if args.output:
        with args.output.open("x", encoding="utf-8") as stream:
            json.dump(report, stream, indent=2)
            stream.write("\n")
    report.pop("stdout", None)
    report.pop("stderr", None)
    for characteristic in report.get("characteristics", []):
        raw = bytes.fromhex(characteristic.pop("value_hex", ""))
        if "read_status" in characteristic:
            characteristic.update(read_bytes=len(raw), nonzero_bytes=sum(bool(v) for v in raw))
    print(json.dumps(report, indent=2))
    if report.get("status") != "Success" or any(c.get("status") == "characteristic_enumeration_failed" for c in report.get("characteristics", [])):
        raise SystemExit(2)


if __name__ == "__main__":
    main()
