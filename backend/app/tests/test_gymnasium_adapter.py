from app.env.gymnasium_adapter import GymnasiumDispatchAdapter
from app.rl.environment import PortEnergyDispatchEnv


def test_adapter_exposes_json_packets_from_real_environment() -> None:
    env = PortEnergyDispatchEnv(split="test", episode_hours=4, render_mode="trajectory")
    adapter = GymnasiumDispatchAdapter(env)

    reset_payload = adapter.reset()
    step_payload = adapter.step([1.0, 0.0, 0.0])

    assert reset_payload["environment_id"] == "PortEnergyDispatchEnv-v1"
    assert reset_payload["info"]["split"] == "test"
    assert len(reset_payload["observation"]) == 12
    assert step_payload["info"]["trajectory_event"]["load_kw"] > 0


def test_adapter_mpc_rollout_renders_only_test_trajectory() -> None:
    env = PortEnergyDispatchEnv(split="test", episode_hours=4, render_mode="trajectory")
    episode = GymnasiumDispatchAdapter(env).run_mpc_episode()

    assert episode["status"] == "tested"
    assert episode["split"] == "test"
    assert episode["episode_steps"] == 4
    assert len(episode["trajectory"]) == 4
