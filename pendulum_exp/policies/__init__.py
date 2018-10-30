"""Policies subpackage."""
from typing import Tuple
from gym import Space
from gym.spaces import Discrete, Box
from abstract import Policy
from policies.discrete import AdvantagePolicy
from policies.continuous import AdvantagePolicy as ContinuousAdvantagePolicy
from models import ContinuousAdvantageMLP, ContinuousPolicyMLP, MLP
from noise import setup_noise
from config import NoiseConfig, PolicyConfig

def setup_policy(observation_space: Space,
                 action_space: Space,
                 policy_config: PolicyConfig,
                 nb_layers: int,
                 batch_size: int,
                 hidden_size: int,
                 noise_config: NoiseConfig,
                 eval_noise_config: NoiseConfig,
                 device) -> Tuple[Policy, Policy]:
    # assume observation space has shape (F,) for now
    nb_state_feats = observation_space.shape[0]
    val_function = MLP(nb_inputs=nb_state_feats, nb_outputs=1,
                       nb_layers=nb_layers, hidden_size=hidden_size).to(device)
    if isinstance(action_space, Discrete):
        adv_function = MLP(nb_inputs=nb_state_feats, nb_outputs=action_space.n,
                           nb_layers=nb_layers, hidden_size=hidden_size).to(device)
        noise = setup_noise(noise_config, network=adv_function,
                            action_shape=(batch_size, action_space.n)).to(device)
        eval_noise = setup_noise(eval_noise_config, network=adv_function,
                                 action_shape=(batch_size, action_space.n)).to(device)
        policy = AdvantagePolicy(
            adv_function=adv_function, val_function=val_function, adv_noise=noise,
            policy_config=policy_config, device=device)
        eval_policy = AdvantagePolicy(
            adv_function=adv_function, val_function=val_function, adv_noise=eval_noise,
            policy_config=policy_config, device=device)

    elif isinstance(action_space, Box):
        nb_actions = action_space.shape[-1]
        adv_function = ContinuousAdvantageMLP(
            nb_state_feats=nb_state_feats, nb_actions=nb_actions,
            nb_layers=nb_layers, hidden_size=hidden_size).to(device)
        policy_function = ContinuousPolicyMLP(
            nb_inputs=nb_state_feats, nb_outputs=nb_actions,
            nb_layers=nb_layers, hidden_size=hidden_size).to(device)
        noise = setup_noise(noise_config, network=policy_function,
                            action_shape=(batch_size, action_space.shape[0]))
        eval_noise = setup_noise(eval_noise_config, network=policy_function,
                                 action_shape=(batch_size, action_space.shape[0]))
        policy = ContinuousAdvantagePolicy(
            adv_function=adv_function, val_function=val_function, policy_function=policy_function,
            policy_noise=noise, policy_config=policy_config, device=device)
        eval_policy = ContinuousAdvantagePolicy(
            adv_function=adv_function, val_function=val_function, policy_function=policy_function,
            policy_noise=eval_noise, policy_config=policy_config, device=device)
    return policy, eval_policy


__all__ = ['AdvantagePolicy', 'ContinuousAdvantagePolicy']