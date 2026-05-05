from workflows.automation.common.run_config import RunConfig

path = r"D:/Development/Software/Python/pyMeCom-automationMod_FJ/examples/power_live_log_com.SineWave_example.json"
cfg = RunConfig.from_json_file(path)

print(f"Loaded run_name={cfg.run_name!r}, steps={len(cfg.steps)}")
for i, step in enumerate(cfg.steps[:3]):
    print(
        i,
        step.name,
        "tec_power_w=", step.tec_power_w,
        "duration_s=", step.duration_s,
        "bath_setpoint_c=", step.bath_setpoint_c,
        "progression_mode=", step.progression_mode,
    )