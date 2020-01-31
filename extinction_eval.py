''' Runs experiments for our alife20 paper, exploring the effect of extinction events on the
complexity of maps generated by a trained RL agent.'''
import os
import shutil
import re
import time

import matplotlib.pyplot as plt
import gym
import numpy as np
import torch
from PIL import Image

import game_of_life
import gym_city
from arguments import get_parser
from envs import VecPyTorch, make_vec_envs
from evaluate import Evaluator
from model import Policy
from utils import get_vec_normalize

#plt.switch_backend('agg')

def parse_cl_args():
    #TODO: away with this function, in theory.
    '''
    Takes arguments from the command line and ignores as many of them as possible.
    '''

    # assume the user passes no args, and these are defaults/dummy
    #TODO: trash all of this
    parser = get_parser()

    parser.add_argument('--non-det', action='store_true', default=False,
                        help='whether to use a non-deterministic policy')
    parser.add_argument('--active-column', default=None, type=int,
                        help='Run only one vertical column of a fractal model to see what it\
                        has learnt independently')
    parser.add_argument('--evaluate', action='store_true', default=False,
                        help='record trained network\'s performance')
    # add any experiment-specific args here
    args = parser.parse_args()
    args.im_render = True
   #args.render = True
    args.random_terrain = False
    args.random_builds = False
    return args



class ExtinctionEvaluator():
    '''Run a series of experiments to evaluate the effect of extinction events on the complexity
    of the behaviour of a trained agent.'''
    def __init__(self, args, im_log_dir):
        self.im_log_dir = im_log_dir
        self.log_dir = args.load_dir
        env_name = args.env_name
        if torch.cuda.is_available() and not args.no_cuda:
            args.cuda = True
            device = torch.device('cuda')
            map_location = torch.device('cuda')
        else:
            args.cuda = False
            device = torch.device('cpu')
            map_location = torch.device('cpu')
        try:
            checkpoint = torch.load(os.path.join(args.load_dir, env_name + '.tar'),
                                    map_location=map_location)
        except FileNotFoundError:
            print('load-dir does not start with valid gym environment id, using command line args')
            env_name = args.env_name
            checkpoint = torch.load(os.path.join(args.load_dir, env_name + '.tar'),
                                map_location=map_location)
        saved_args = checkpoint['args']
        past_frames = checkpoint['n_frames']
        args.past_frames = past_frames
        env_name = saved_args.env_name

        if 'Micropolis' in env_name:
            args.power_puzzle = saved_args.power_puzzle

        if not args.evaluate and not 'GoLMulti' in env_name:
            # assume we just want to observe/interact w/ a single env.
            args.num_proc = 1
        dummy_args = args
        envs = make_vec_envs(env_name, args.seed + 1000, args.num_processes,
                            None, args.load_dir, args.add_timestep, device=device,
                            allow_early_resets=False,
                            args=dummy_args)
        print(args.load_dir)

        if isinstance(envs.observation_space, gym.spaces.Discrete):
            in_width = 1
            num_inputs = envs.observation_space.n
        elif isinstance(envs.observation_space, gym.spaces.Box):
            if len(envs.observation_space.shape) == 3:
                in_w = envs.observation_space.shape[1]
                in_h = envs.observation_space.shape[2]
            else:
                in_w = 1
                in_h = 1
            num_inputs = envs.observation_space.shape[0]

        if isinstance(envs.action_space, gym.spaces.Discrete):
            out_w = 1
            out_h = 1
            num_actions = int(envs.action_space.n // (in_w * in_h))
           #if 'Micropolis' in env_name:
           #    num_actions = env.venv.venv.envs[0].num_tools
           #elif 'GameOfLife' in env_name:
           #    num_actions = 1
           #else:
           #    num_actions = env.action_space.n
        elif isinstance(envs.action_space, gym.spaces.Box):
            out_w = envs.action_space.shape[0]
            out_h = envs.action_space.shape[1]
            num_actions = envs.action_space.shape[-1]
        # We need to use the same statistics for normalization as used in training
        #actor_critic, ob_rms = \
        #            torch.load(os.path.join(args.load_dir, args.env_name + ".pt"))

        if saved_args.model == 'fractal':
            saved_args.model = 'FractalNet'
        actor_critic = Policy(envs.observation_space.shape, envs.action_space,
                base_kwargs={'map_width': args.map_width,
                             'recurrent': args.recurrent_policy,
                            'in_w': in_w, 'in_h': in_h, 'num_inputs': num_inputs,
                    'out_w': out_w, 'out_h': out_h },
                             curiosity=args.curiosity, algo=saved_args.algo,
                             model=saved_args.model, args=saved_args)
        actor_critic.to(device)
        torch.nn.Module.dump_patches = True
        actor_critic.load_state_dict(checkpoint['model_state_dict'])
        ob_rms = checkpoint['ob_rms']

        if 'fractal' in args.model.lower():
            new_recs = args.n_recs - saved_args.n_recs

            for nr in range(new_recs):
                actor_critic.base.auto_expand()
            print('expanded network:\n', actor_critic.base)

            if args.active_column is not None \
                    and hasattr(actor_critic.base, 'set_active_column'):
                actor_critic.base.set_active_column(args.active_column)
        vec_norm = get_vec_normalize(envs)

        if vec_norm is not None:
            vec_norm.eval()
            vec_norm.ob_rms = ob_rms
        self.actor_critic = actor_critic
        self.envs = envs
        self.args = args

    def run_experiment(self, n_epis, max_step, map_width, extinction_type, extinction_prob,
            extinction_dels):
        '''Evaluate the effect of a single type of extinction event (or none).'''
        args = self.args
        actor_critic = self.actor_critic
        envs = self.envs
        im_log_dir = '{}/xttyp:{}_stp:{}'.format(
                self.im_log_dir,
                extinction_type,
               #extinction_prob,
               #map_width,
                max_step
                )
        envs.venv.venv.set_log_dir(im_log_dir)
        # adjust envs in general
        envs.venv.venv.setMapSize(map_width, max_step=max_step, render=args.render)
        if extinction_type is not None:
            # adjust extinguisher wrapper
            envs.venv.venv.set_extinction_type(extinction_type, extinction_prob, extinction_dels)
        # adjust image render wrapper
        envs.venv.venv.reset_episodes(im_log_dir)
        envs.venv.venv.init_storage()
        recurrent_hidden_states = torch.zeros(1, actor_critic.recurrent_hidden_state_size)
        masks = torch.zeros(1, 1)
        obs = envs.reset()
        #obs = torch.Tensor(obs)
        player_act = None
        n_episode = 0

        while n_episode < n_epis:
            with torch.no_grad():
                value, action, _, recurrent_hidden_states = actor_critic.act(
                    obs, recurrent_hidden_states, masks, deterministic=not args.non_det,
                    player_act=player_act)
            # Observe reward and next obs
            obs, reward, done, infos = envs.step(action)
            if args.render:
                envs.venv.venv.render()

            if done.any():
                n_episode += np.sum(done.astype(int))
            player_act = None

            if infos[0]:
                if 'player_move' in infos[0].keys():
                    player_act = infos[0]['player_move']
           #masks.fill_(0.0 if done else 1.0)
        envs.reset()

#def run_experiment():
#    '''Measure True under various conditions.'''
#    map_sizes = self.map_sizes
#    extinction_types = self.extinction_types
#    extinction_intervals = self.extinction_intervals
#    evaluator = ExtinctionEvaluator()
#
#    for map_size in map_sizes:
#        for extinction_type in extinction_types:
#            for extinction_interval in extinction_intervals:
#                evaluator.run_experiment(map_size, extinction_type, extinction_interval)

def get_xy(exp_dir):
    '''Plot the mean episode by mean size of the functional jpeg in terms of timestep.
    - exp_dir: location of images
    Return xy coordinates of mean episode
    '''
    ims = os.listdir(exp_dir)
    # map timesteps to a tuple (mean_size, num_ims)
    step2size = {}

    for im in ims:
        step_search = re.search(r'([\d]+)\.jpg', im)
        step = step_search.group(1)
        im_path = os.path.join(exp_dir, im)
        size = os.stat(im_path).st_size

        if step in step2size:
            mean_size, num_ims = step2size[step]
            mean_size = (mean_size * num_ims + size) / (num_ims + 1)
            num_ims += 1
            step2size[step] = (mean_size, num_ims)
        else:
            step2size[step] = (size, 1)
    xs = []
    ys = []
    for x, (y, _) in step2size.items():
        xs += [x]
        ys += [y]
    xy = zip(xs, ys)
    xy = sorted(xy, key = lambda x: int(x[0]))
    xs, ys = zip(*xy)
    return xs, ys

def visualize_experiments(log_dir):
    '''Visualize results from extinction-compressibility experiments.
     - load-dir: stores folder of experiments, within which are compressed images named by
    '''
    log_dir = log_dir
    xtinct_dirs = os.listdir(log_dir)
    xt_dir_paths = [os.path.join(log_dir, xt_dir) for xt_dir in xtinct_dirs]
    # make sure the order of local and global paths correspond
    dirs_types = zip(xtinct_dirs, xt_dir_paths)
    dirs_types = sorted(dirs_types, key = lambda x: str(x[0]))
    xtinct_dirs, xt_dir_paths = zip(*dirs_types)
    xt_ims = [os.listdir(xt_dir) for xt_dir in xt_dir_paths if not os.path.isfile(xt_dir) ]

    for i, trial_name in enumerate(xtinct_dirs):
        print(trial_name)
        srch_xttyp = re.search(r'xttyp\:([a-zA-Z]+)', trial_name)
        if srch_xttyp is None:
            continue
        xt_type = srch_xttyp.group(1)
        xt_dir = xt_dir_paths[i]
        exp_title = ' '.join(xt_dir.split('/')[-2:])
        if os.path.isfile(xt_dir):
            continue
        x, y = get_xy(xt_dir)
        exp_plot, = plt.plot(x, y)
        print(xt_type)
        exp_plot.set_label(xt_type)

    srch_xtprob = re.search(r'xtprob\:(\d.[\d]+)', log_dir)
    xt_prob = srch_xtprob.group(1)
    xt_interval = int(1 / float(xt_prob))
    graph_title = 'extinction interval = {}'.format(xt_interval)
    plt.title(graph_title)
    plt.xlabel('timesteps')
    plt.ylabel('bytes per jpg')
    plt.xticks([25 * i for i in range(5)])
    plt.legend()
    plt.savefig(os.path.join(log_dir, '{}.png'.format(graph_title)), format='png')
       #plt.show()

class ExtinctionExperimenter():
    '''
    Coordinate between experimentation and visualization.
    '''
    def __init__(self, log_dir):
        args = parse_cl_args()
        env_name = log_dir.split('/')[-1].split('_')[0]
        args.env_name = env_name
        # Experiment global parameters
        self.n_epis = 20
        self.max_step = [1000]
        self.map_sizes = [
                16,
               #32,
               #64
                ]
        self.xt_types = [
                None,
                'age',
                'spatial',
                'random'
                ]
        # TODO: automate xt_probs
        self.xt_probs = [args.extinction_prob]
        self.xt_dels = [15]
        self.map_sizes = [args.map_width]
       #self.xt_probs = [
       #        0.005,
       #       #0.01,
       #       #0.05,
       #       #0.1
       #        ]
        exp_name = 'test_map:{}_xtprob:{}_xtdels:{}'.format(
                self.map_sizes[0],
                float(self.xt_probs[0]),
                self.xt_dels[0])
        self.log_dir = log_dir
        args.load_dir = log_dir
        im_log_dir = os.path.join(log_dir, exp_name)
        try:
            os.mkdir(im_log_dir)
        except FileExistsError:
           #shutil.rmtree(im_log_dir)
           #os.mkdir(im_log_dir)
            pass
        self.im_log_dir = im_log_dir
        self.evaluator = ExtinctionEvaluator(args, im_log_dir)

    def run_experiments(self):
        '''Run experiments and produce data.'''
        evaluator = self.evaluator
        for mst in self.max_step:
            for msz in self.map_sizes:
                for xtd in self.xt_dels:
                    for xtt in self.xt_types:
                        if xtt is None:
                            xtp = 0
                            evaluator.run_experiment(self.n_epis, mst, msz, xtt, xtp, xtd)
                        else:
                            for xtp in self.xt_probs:
                                evaluator.run_experiment(self.n_epis, mst, msz, xtt, xtp, xtd)

    def visualize_experiments(self):
        '''
        Visualize compressibility data stored in subfolders of the current directory.
        '''
        return visualize_experiments(self.im_log_dir)


if __name__ == "__main__":
    VIS_ONLY = False
   #VIS_ONLY = True
    LOG_DIR = os.path.abspath(os.path.join(
        'trained_models',
        'a2c_FractalNet_drop',
        'MicropolisEnv-v0_w16_1000s_noExtinct.bkp',
        ))
    EXPERIMENTER = ExtinctionExperimenter(LOG_DIR)

    #TODO: hacky; detect incomplete folders automatically,
    #     should save numpy object w/ stats in folder
    if not VIS_ONLY:
        try:
            EXPERIMENTER.run_experiments()
        # broadcast problem when sizing up map #TODO: adjust vec_envs to prevent this
        except ValueError as ve:
            print(ve)
    EXPERIMENTER.visualize_experiments()
