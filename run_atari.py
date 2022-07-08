import subprocess
import argparse
import json
import copy
import wandb
import itertools
import multiprocessing as mp
from multiprocessing import Pool
from src.envs.atari import *
from run_finetune import run
import numpy as np


if __name__ == '__main__':
    parser = argparse.ArgumentParser(allow_abbrev=False)
    parser.add_argument('--exp_name',     type=str,    default='otr',  help='name for the parallel runs')
    parser.add_argument('--config_dir',   type=str,    default='atari')
    parser.add_argument('--config_name',  type=str,    default='otr_nature') 
    parser.add_argument('--num_seeds',     type=int,   default=3)
    parser.add_argument('--num_devices',   type=int,   default=4)
    parser.add_argument('--num_exp_per_device',  type=int,  default=4)
    parser.add_argument('--overrides',    action='append',  default=[]) #'agent.num_timesteps=2500', 'agent.eval_every=2500']) 
    
    args = vars(parser.parse_args())
    seeds = np.arange(args.pop('num_seeds'))
    games = list(atari_human_scores.keys())
    num_devices = args.pop('num_devices')
    num_exp_per_device = args.pop('num_exp_per_device')
    pool_size = num_devices * num_exp_per_device 


    # snake case to camel case
    # name = ''.join(word.title() for word in name.split('_'))

    # create configurations for child run
    experiments = []
    device_id = 0
    for seed, game in itertools.product(*[seeds, games]):
        exp = copy.deepcopy(args)
        exp_name = exp.pop('exp_name')
        device_id = int(device_id % num_devices)
        exp['overrides'].append('exp_name=' + exp_name)
        exp['overrides'].append('seed=' + str(seed))
        exp['overrides'].append('env.game=' + str(game))
        exp['overrides'].append('device=' + 'cuda:' + str(device_id))

        experiments.append(exp)
        device_id += 1
        print(exp)

    # run parallell experiments
    # maxtasksperchild=1 -> no.of workers = no.of experiements
    # maxtasksperchild=None -> no.of workers = pool size
    # https://docs.python.org/3.5/library/multiprocessing.html#contexts-and-start-methods
    # mp.set_start_method('spawn') 
    pool = Pool(pool_size, maxtasksperchild=1)
    results = pool.map(run, experiments, chunksize=1)
    pool.close()

    # get metrics & artifacts from each logger
    scores_per_game, norm_scores_per_game = {}, {}
    artifacts_dict = {}
    for game in games:
        scores_per_game[game] = []
        norm_scores_per_game[game] = []

    for logger in results:
        game = logger.get_game_name()
        score = logger.get_mean_eval_score()
        scores_per_game[game].append(float(score))

        # norm-score
        random_score = atari_random_scores[game] 
        human_score = atari_human_scores[game]
        norm_score = (score - random_score) / (human_score - random_score)
        norm_scores_per_game[game].append(float(norm_score))

        artifacts = logger.get_artifacts()
        for path, name in artifacts.items():
            artifacts_dict[path] = name

    ####################
    # wandb
    wandb.init(project='atari100k', 
               config=args,
               group=args['exp_name'],
               settings=wandb.Settings(start_method="thread"))  
    artifact = wandb.Artifact(name=args['exp_name'], type='model')

    # log metrics as table
    columns= ["id", "game", "score", "HNS_score"]
    table = wandb.Table(columns=columns)
    
    idx = 0
    mean_score_per_game = []
    mean_norm_score_per_game = []
    for game in games:
        scores = scores_per_game[game]
        norm_scores = norm_scores_per_game[game]
        mean_score_per_game.append(np.mean(scores))
        mean_norm_score_per_game.append(np.mean(norm_scores))

        for s_idx in seeds:
            score = scores[s_idx]
            norm_score = norm_scores[s_idx]
            table.add_data(idx, game, score, norm_score)
            idx += 1
    
    table.add_data(idx, 'median', np.median(mean_score_per_game), np.median(mean_norm_score_per_game))
    table.add_data(idx+1, 'mean', np.mean(mean_score_per_game), np.mean(mean_norm_score_per_game))
    artifact.add(table, 'result')

    # save models
    for path, name in artifacts_dict.items():
        artifact.add_file(path, name=name)
    
    wandb.run.finish_artifact(artifact)
