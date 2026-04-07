#!/usr/bin/env python3
"""GPU topology and PCIe discovery tests.

This test validates that:
1) GPUs appear in `nvidia-smi topo -m` output.
2) NVIDIA devices are visible on the PCIe bus via `lspci`.
3) PCIe link speed information is present in verbose PCIe output.
"""

import re
import subprocess
import unittest
from typing import Dict, List


class TestGPUEnumerationAndTopology(unittest.TestCase):
    """Validate GPU discovery and PCIe topology visibility."""

    @staticmethod
    def _run_command(cmd: List[str], shell: bool = False) -> subprocess.CompletedProcess:
        return subprocess.run(
            cmd,
            shell=shell,
            text=True,
            capture_output=True,
            timeout=30,
            check=False,
        )

    @staticmethod
    def _parse_gpu_rows_from_topo(output: str) -> List[str]:
        gpu_rows: List[str] = []
        for line in output.splitlines():
            if re.match(r"^GPU\d+\s+", line.strip()):
                gpu_rows.append(line.strip())
        return gpu_rows

    @staticmethod
    def _extract_nvidia_pcie_speeds(lspci_vv_output: str) -> List[Dict[str, str]]:
        devices: List[Dict[str, str]] = []
        blocks = lspci_vv_output.split("\n\n")

        for block in blocks:
            if "nvidia" not in block.lower():
                continue

            lines = [ln for ln in block.splitlines() if ln.strip()]
            if not lines:
                continue

            header = lines[0].strip()
            bus = header.split()[0] if header else "unknown"

            speed = "unknown"
            width = "unknown"

            for ln in lines:
                m = re.search(r"LnkSta:\s*Speed\s*([0-9.]+GT/s),\s*Width\s*x(\d+)", ln)
                if m:
                    speed = m.group(1)
                    width = f"x{m.group(2)}"
                    break

                m_cap = re.search(r"LnkCap:\s*Port\s*#\d+,\s*Speed\s*([0-9.]+GT/s),\s*Width\s*x(\d+)", ln)
                if m_cap:
                    speed = m_cap.group(1)
                    width = f"x{m_cap.group(2)}"

            devices.append(
                {
                    "bus": bus,
                    "speed": speed,
                    "width": width,
                    "header": header,
                }
            )

        return devices

    def test_pcie_topology_discovery(self) -> None:
        topo = self._run_command(["nvidia-smi", "topo", "-m"])
        self.assertEqual(
            topo.returncode,
            0,
            msg=(
                "Failed to run 'nvidia-smi topo -m'. "
                f"stderr: {topo.stderr.strip() or '<empty>'}"
            ),
        )

        gpu_rows = self._parse_gpu_rows_from_topo(topo.stdout)
        self.assertGreater(
            len(gpu_rows),
            0,
            msg=(
                "No GPU rows discovered in 'nvidia-smi topo -m' output. "
                "Ensure NVIDIA GPUs are present and drivers are loaded."
            ),
        )

        # Requested command in ask was lscpi; actual Linux utility is lspci.
        lspci_nvidia = self._run_command(["lspci -v | grep -i nvidia"], shell=True)
        self.assertEqual(
            lspci_nvidia.returncode,
            0,
            msg=(
                "'lspci -v | grep -i nvidia' did not find NVIDIA devices on PCIe bus. "
                f"stderr: {lspci_nvidia.stderr.strip() or '<empty>'}"
            ),
        )

        nvidia_lines = [ln for ln in lspci_nvidia.stdout.splitlines() if ln.strip()]
        self.assertGreater(
            len(nvidia_lines),
            0,
            msg="No NVIDIA lines found in lspci output.",
        )

        lspci_vv = self._run_command(["lspci", "-vv"])
        self.assertEqual(
            lspci_vv.returncode,
            0,
            msg=f"Failed to run 'lspci -vv'. stderr: {lspci_vv.stderr.strip() or '<empty>'}",
        )

        nvidia_devices = self._extract_nvidia_pcie_speeds(lspci_vv.stdout)
        self.assertGreater(
            len(nvidia_devices),
            0,
            msg="No NVIDIA device blocks found in lspci -vv output.",
        )

        speeds = [d["speed"] for d in nvidia_devices if d["speed"] != "unknown"]
        self.assertGreater(
            len(speeds),
            0,
            msg=(
                "NVIDIA devices were found, but PCIe speed could not be parsed from LnkSta/LnkCap. "
                "Check that lspci verbose output exposes link status."
            ),
        )

        # Helpful detail in assertion output when cross-checking host state in CI logs.
        self.assertGreaterEqual(
            len(nvidia_lines),
            len(gpu_rows),
            msg=(
                "Fewer NVIDIA devices on PCIe bus than GPUs in nvidia-smi topology. "
                f"topo_gpus={len(gpu_rows)}, lspci_nvidia={len(nvidia_lines)}, speeds={speeds}"
            ),
        )


if __name__ == "__main__":
    unittest.main()
