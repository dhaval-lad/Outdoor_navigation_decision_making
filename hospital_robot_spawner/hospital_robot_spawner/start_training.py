#!usr/bin/env python3

import rclpy
from rclpy.node import Node
from gym.envs.registration import register
from hospital_robot_spawner.hospitalbot_env import HospitalBotEnv
import gym
from stable_baselines3 import A2C, PPO, DQN, DDPG
from stable_baselines3.common.env_checker import check_env
from stable_baselines3.common.callbacks import EvalCallback, StopTrainingOnRewardThreshold
from gym.wrappers import NormalizeReward
import os
import optuna
from stable_baselines3.common.evaluation import evaluate_policy

class TrainingNode(Node):

    def __init__(self):
        super().__init__("hospitalbot_training", allow_undeclared_parameters=True, automatically_declare_parameters_from_overrides=True)

        # Defines which method for training "random_agent", "training", "retraining" or "hyperparam_tuning"
        self._training_mode = "hyperparam_tuning"

        # Get training parameters from Yaml file
        #self.test = super().get_parameter('test').value
        #self.get_logger().info("Test parameter: " + str(self.test))

def main(args=None):

    # Initialize the training node to get the desired parameters
    rclpy.init()
    node = TrainingNode()
    node.get_logger().info("Training node has been created")

    # Create the dir where the trained RL models will be saved
    pkg_dir = '/home/tommaso/ros2_ws/src/hospital_robot_spawner'
    trained_models_dir = os.path.join(pkg_dir, 'rl_models')
    log_dir = os.path.join(pkg_dir, 'logs')
    
    # If the directories do not exist we create them
    if not os.path.exists(trained_models_dir):
        os.makedirs(trained_models_dir)
    if not os.path.exists(log_dir):
        os.makedirs(log_dir)

    # First we register the gym environment created in hospitalbot_env module
    register(
        id="HospitalBotEnv-v0",
        entry_point="hospital_robot_spawner.hospitalbot_env:HospitalBotEnv",
        max_episode_steps=100,
    )

    node.get_logger().info("The environment has been registered")

    env = NormalizeReward(gym.make('HospitalBotEnv-v0'))
    episodes = 10

    # Sample Observation and Action space for Debugging
    #node.get_logger().info("Observ sample: " + str(env.observation_space.sample()))
    #node.get_logger().info("Action sample: " + str(env.action_space.sample()))

    # Here we check if the custom gym environment is fine
    check_env(env)
    node.get_logger().info("Environment check finished")

    # Now we create two callbacks which will be executed during training
    stop_callback = StopTrainingOnRewardThreshold(reward_threshold=900, verbose=1)
    eval_callback = EvalCallback(env, callback_on_new_best=stop_callback, eval_freq=50000, best_model_save_path=trained_models_dir)
    
    if node._training_mode == "random_agent":
        ## Execute a random agent
        node.get_logger().info("Starting the RANDOM AGENT now")
        for ep in range(episodes):
            obs = env.reset()
            done = False
            while not done:
                obs, reward, done, info = env.step(env.action_space.sample())
                node.get_logger().info("Polar coordinates: " + str(obs["agent"]))
                node.get_logger().info("Reward at step " + ": " + str(reward))
    
    elif node._training_mode == "training":
        ## Train the model
        model = PPO("MultiInputPolicy", env, verbose=1, tensorboard_log=log_dir)
        # Execute training
        model.learn(total_timesteps=int(2000000), reset_num_timesteps=False, callback=eval_callback, tb_log_name="PPO_100TS_LR3-3_2000000_adaptive_rand_targ")
        # Save the trained model
        model.save(f"{trained_models_dir}/PPO_100TS_LR3-3_2000000_adaptive_rand_targ")
    
    elif node._training_mode == "retraining":
        ## Re-train an existent model
        node.get_logger().info("Retraining an existent model")
        # Path in which we find the model
        trained_model_path = os.path.join(pkg_dir, 'rl_models', 'best_model.zip')
        # Here we load the rained model
        #custom_obs = {'learning_rate': 0.000003, 'ent_coef': 0.01}
        model = PPO.load(trained_model_path, env=env) #, custom_objects=custom_obs)
        # Execute training
        model.learn(total_timesteps=int(2000000), reset_num_timesteps=False, callback=eval_callback, tb_log_name="PPO_100TS_LR3-5_2000000_adaptive_rand_targ")
        # Save the trained model
        model.save(f"{trained_models_dir}/PPO_100TS_LR3-5_2000000_adaptive_rand_targ")

    elif node._training_mode == "hyperparam_tuning":
        # Delete previously created environment
        env.close()
        del env
        # Hyperparameter tuning using Optuna
        study = optuna.create_study(direction='maximize')
        study.optimize(optimize_agent, n_trials=10, n_jobs=1)
        # Print best params
        node.get_logger().info("Best Hyperparameters: " + str(study.best_params))

    # Shutting down the node
    node.get_logger().info("The training is finished, now the node is destroyed")
    node.destroy_node()
    rclpy.shutdown()

def optimize_ppo(trial):
    ## This method defines the range of hyperparams to search fo the best tuning
    return {
        'n_steps': trial.suggest_int('n_steps', 2048, 8192),
        'gamma': trial.suggest_loguniform('gamma', 0.8, 0.9999),
        'learning_rate': trial.suggest_loguniform('learning_rate', 1e-6, 1e-3),
        'clip_range': trial.suggest_uniform('clip_range', 0.1, 0.4),
        'gae_lambda': trial.suggest_uniform('gae_lambda', 0.8, 0.99),
        'ent_coef': trial.suggest_loguniform('ent_coef', 0.00000001, 0.1),
        'vf_coef': trial.suggest_uniform('vf_coef', 0, 1),
    }

def optimize_agent(trial):
    ## This method is used to optimize the hyperparams for our problem
    try:
        # Create environment
        env_opt = NormalizeReward(gym.make('HospitalBotEnv-v0'))
        # Setup dirs
        PKG_DIR = '/home/tommaso/ros2_ws/src/hospital_robot_spawner'
        LOG_DIR = os.path.join(PKG_DIR, 'logs')
        SAVE_PATH = os.path.join(PKG_DIR, 'tuning', 'trial_{}_best_model'.format(trial.number))
        # Setup the parameters
        model_params = optimize_ppo(trial)
        # Setup the model
        model = PPO("MultiInputPolicy", env_opt, tensorboard_log=LOG_DIR, verbose=0, **model_params)
        model.learn(total_timesteps=100000)
        # Evaluate the model
        mean_reward, _ = evaluate_policy(model, env_opt, n_eval_episodes=20)
        # Close env and delete
        env_opt.close()
        del env_opt

        model.save(SAVE_PATH)

        return mean_reward

    except Exception as e:
        return -10000

if __name__ == "__main__":
    main()