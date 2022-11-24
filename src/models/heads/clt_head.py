import torch.nn as nn
import torch.nn.functional as F
import torch, numpy as np
from einops import rearrange
from .base import BaseHead
from src.models.layers import *
from src.common.train_utils import xavier_uniform_init, init_normalization


class CLTHead(BaseHead):
    name = 'clt'
    def __init__(self, 
                 obs_shape, 
                 action_size, 
                 t_step, 
                 in_dim, 
                 proj_dim, 
                 dec_num_layers):
        
        super().__init__()
        self.t_step = t_step
        self.in_dim = in_dim
        self.proj_dim = proj_dim
        
        self.obs_in = nn.Linear(in_dim, proj_dim)
        self.act_in = nn.Embedding(action_size, proj_dim)
        self.rew_in = nn.Linear(1, proj_dim) 
        self.rtg_in = nn.Linear(1, proj_dim)
        
        self.dec_norm = nn.LayerNorm(proj_dim)
        self.decoder = TransDet(obs_shape=obs_shape, 
                                action_size=action_size,
                                hid_dim=proj_dim,
                                num_layers=dec_num_layers)
        proj_in_dim = proj_dim
                    
        self.projector = nn.Sequential(nn.Linear(proj_in_dim, proj_dim), 
                                       nn.BatchNorm1d(proj_dim), 
                                       nn.ReLU(), 
                                       nn.Linear(proj_dim, proj_dim))
                                       #nn.BatchNorm1d(proj_dim, affine=False))
        
        self.predictor = nn.Sequential(nn.Linear(proj_dim, proj_dim), 
                                       nn.BatchNorm1d(proj_dim), 
                                       nn.ReLU(), 
                                       nn.Linear(proj_dim, proj_dim))
        
        self.act_predictor = nn.Sequential(nn.Linear(proj_dim, proj_dim), 
                                           nn.ReLU(), 
                                           nn.Linear(proj_dim, action_size))
        
        self.idm_predictor = nn.Sequential(nn.Linear(2*proj_dim, proj_dim), 
                                           nn.ReLU(), 
                                           nn.Linear(proj_dim, action_size))
        
        # assume that reward lies under (-1~1)
        self.rew_predictor = nn.Sequential(nn.Linear(proj_dim, proj_dim), 
                                           nn.ReLU(), 
                                           nn.Linear(proj_dim, 1),
                                           nn.Tanh()) 
        self.rtg_predictor = nn.Sequential(nn.Linear(proj_dim, proj_dim), 
                                           nn.ReLU(), 
                                           nn.Linear(proj_dim, 1))
    def decode(self, x, dataset_type):        
        n, t, d = x['obs'].shape
        
        if d != self.proj_dim:
            obs = self.obs_in(x['obs'])
            obs = self.dec_norm(obs)
        else:
            obs = x['obs']
        
        # embedding
        act, rew, rtg = None, None, None
        if dataset_type == 'video':
            # x = (o_1, o_2, ...)
            T = t
            
        elif dataset_type == 'demonstration':
            # x = (o_1, a_1, o_2, a_2, ...)
            T = 2 * t
            act = self.act_in(x['act'])
            
        elif dataset_type == 'trajectory':
            # x = (o_1, a_1, r_1, R_1, o_2, a_2, r_2, R_2, ...)
            T = 4 * t
            act = self.act_in(x['act'])
            rew = self.rew_in(x['rew'].unsqueeze(-1))
            rtg = self.rtg_in(x['rtg'].unsqueeze(-1))
            
        else:
            raise NotImplemented
        
        # decoding
        attn_mask = 1 - torch.ones((n, T, T), device=(obs.device)).tril_()
        x = self.decoder(obs, act, rew, rtg, attn_mask, dataset_type)

        # prediction
        obs, act, rew, rtg = None, None, None, None
        if dataset_type == 'video':
            # o_t -> o_t+1
            obs = x
            
        elif dataset_type == 'demonstration':
            # o_t -> a_t, a_t -> o_(t+1)
            obs = x[:, torch.arange(t)*2+1, :] # o_(t+1), ... o_(T+1)
            act = x[:, torch.arange(t)*2, :]   # a_(t), ... a_(T)
            
            act = self.act_predictor(act)
            
        elif dataset_type == 'trajectory':
            # o_t -> a_t, a_t -> r_t, r_t -> o_(t+1)
            obs = x[:, torch.arange(t)*4+3, :] # o_(t+1), ... o_(T+1)
            act = x[:, torch.arange(t)*4, :]   # a_(t), ... a_(T)
            rew = x[:, torch.arange(t)*4+1, :] # r_(t), ... r_(T)
            rtg = x[:, torch.arange(t)*4+2, :] # R_(t), ... R_(T)
            
            act = self.act_predictor(act)
            rew = self.rew_predictor(rew)
            rtg = self.rtg_predictor(rtg)
            
        else:
            raise NotImplemented
        
        x = {'obs': obs,
             'act': act,
             'rew': rew, 
             'rtg': rtg}
        
        return x
    
    def obs_to_latent(self, x):
        n, t, d = x.shape
        x = self.obs_in(x)
        x = self.dec_norm(x)
        
        return x

    def project(self, x):
        n, t, d = x.shape
        x = rearrange(x, 'n t d-> (n t) d')
        x = self.projector(x)
        x = rearrange(x, '(n t) d-> n t d', t=t)
        return x

    def predict(self, x):
        n, t, d = x.shape
        x = rearrange(x, 'n t d-> (n t) d')
        x = self.predictor(x)
        x = rearrange(x, '(n t) d-> n t d', t=t)
        return x

    def forward(self, x):
        info = {}
        return (x, info)
