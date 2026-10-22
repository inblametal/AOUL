"""
Actuator Thermal & Battery Power Envelope Simulator.
Calculates motor Joule heating, winding thermal saturation, duty cycle limits,
and battery discharge endurance for mobile robots and manipulators.
"""

from dataclasses import dataclass
import math
from typing import Any, Dict


@dataclass
class MotorThermalReport:
    torque_nm: float
    angular_velocity_rad_s: float
    current_amps: float
    joule_loss_watts: float
    mechanical_power_watts: float
    total_electrical_power_watts: float
    steady_state_temp_c: float
    transient_temp_c: float
    thermal_status: str  # "NOMINAL", "WARNING_OVERHEAT", "CRITICAL_BURN"
    max_safe_duty_cycle_pct: float
    battery_run_time_hours: float
    advisories: list


class PowerThermalEngine:
    """Simulates motor electro-thermal dynamics and battery runtime."""

    @staticmethod
    def calculate_motor_and_power(
        torque_nm: float,
        speed_rad_s: float,
        run_duration_min: float = 15.0,
        motor_resistance_ohms: float = 0.85,
        torque_constant_kt: float = 0.12,  # Nm/A
        thermal_resistance_rth: float = 1.8,  # °C/Watt
        thermal_time_constant_sec: float = 480.0,  # ~8 mins
        ambient_temp_c: float = 25.0,
        max_winding_temp_c: float = 90.0,
        battery_voltage: float = 24.0,  # 24V LiFePO4 / Li-ion
        battery_capacity_ah: float = 15.0,  # 15Ah (360Wh)
        auxiliary_power_watts: float = 25.0,  # Compute (Nvidia Jetson / NUC) + LiDAR
    ) -> Dict[str, Any]:
        # Current from torque: I = torque / Kt
        current_a = abs(torque_nm) / torque_constant_kt if torque_constant_kt > 0 else 0.0

        # Copper / Joule heating loss: P_loss = I^2 * R
        joule_loss_w = (current_a ** 2) * motor_resistance_ohms

        # Mechanical output power: P_mech = tau * omega
        mech_power_w = abs(torque_nm * speed_rad_s)

        # Total electrical power consumed by actuator
        actuator_elec_power_w = mech_power_w + joule_loss_w

        # Total robot system power (actuator + onboard sensors & compute)
        total_system_power_w = actuator_elec_power_w + auxiliary_power_watts

        # Steady-state temperature rise: Delta_T = P_loss * R_th
        delta_t_ss = joule_loss_w * thermal_resistance_rth
        t_steady_state = ambient_temp_c + delta_t_ss

        # Transient temperature after run duration
        t_seconds = run_duration_min * 60.0
        exp_factor = math.exp(-t_seconds / thermal_time_constant_sec) if thermal_time_constant_sec > 0 else 1.0
        t_transient = ambient_temp_c + delta_t_ss * (1.0 - exp_factor)

        # Thermal status
        advisories = []
        if t_transient >= max_winding_temp_c:
            thermal_status = "CRITICAL_BURN"
            advisories.append(f"Actuator temperature ({t_transient:.1f}°C) exceeds rated insulation limit ({max_winding_temp_c}°C). Thermal cutoff or lower torque required.")
        elif t_transient >= (max_winding_temp_c - 15.0):
            thermal_status = "WARNING_OVERHEAT"
            advisories.append(f"Actuator running hot ({t_transient:.1f}°C). Continuous operation will reach thermal saturation ({t_steady_state:.1f}°C).")
        else:
            thermal_status = "NOMINAL"
            advisories.append(f"Actuator within nominal thermal envelope ({t_transient:.1f}°C / {max_winding_temp_c}°C max).")

        # Max safe continuous duty cycle to stay below max_winding_temp
        max_allowable_loss = max(0.0, (max_winding_temp_c - ambient_temp_c) / thermal_resistance_rth) if thermal_resistance_rth > 0 else 0.0
        if joule_loss_w > 0:
            safe_duty_cycle = min(100.0, max(0.0, (max_allowable_loss / joule_loss_w) * 100.0))
        else:
            safe_duty_cycle = 100.0

        if safe_duty_cycle < 100.0:
            advisories.append(f"Maximum continuous duty cycle limited to {safe_duty_cycle:.0f}% to prevent thermal runaway.")

        # Battery runtime
        battery_energy_wh = battery_voltage * battery_capacity_ah * 0.85  # 85% depth of discharge safe buffer
        battery_runtime_hours = (battery_energy_wh / total_system_power_w) if total_system_power_w > 0 else 99.0

        return {
            "torque_nm": round(torque_nm, 3),
            "speed_rad_s": round(speed_rad_s, 2),
            "speed_rpm": round(speed_rad_s * 9.5493, 1),
            "current_a": round(current_a, 2),
            "joule_loss_w": round(joule_loss_w, 2),
            "mech_power_w": round(mech_power_w, 2),
            "actuator_power_w": round(actuator_elec_power_w, 2),
            "total_system_power_w": round(total_system_power_w, 2),
            "steady_state_temp_c": round(t_steady_state, 1),
            "transient_temp_c": round(t_transient, 1),
            "max_rated_temp_c": max_winding_temp_c,
            "thermal_status": thermal_status,
            "safe_duty_cycle_pct": round(safe_duty_cycle, 1),
            "battery_energy_wh": round(battery_energy_wh, 1),
            "battery_runtime_hours": round(battery_runtime_hours, 2),
            "advisories": advisories,
        }
