from gym.envs.registration import register
import gym_micropolis.envs.tile_map
import gym_micropolis.envs.micropolis_control
import gym_micropolis.envs.micropolis_env

register(
    id='MicropolisEnv-v0',
    entry_point='gym_micropolis.envs:MicropolisEnv',
)

