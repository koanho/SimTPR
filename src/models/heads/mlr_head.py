import torch.nn as nn
import torch.nn.functional as F
import torch, numpy as np
from einops import rearrange
from .base import BaseHead
from src.models.layers import *
from src.common.train_utils import init_normalization
from src.common.vit_utils import get_1d_sincos_pos_embed_from_grid


class MLRHead(BaseHead):
    name = 'mlr'
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
        
        self.mask_token = nn.Parameter(torch.zeros(1, 1, proj_dim))
        self.obs_in = nn.Linear(in_dim, proj_dim)
        self.act_in = nn.Embedding(action_size, proj_dim)
        
        self.dec_norm = nn.LayerNorm(proj_dim)
        self.decoder = TransDet(obs_shape=obs_shape, 
                                action_size=action_size,
                                hid_dim=proj_dim,
                                num_layers=dec_num_layers)
                    
        self.projector = nn.Sequential(nn.Linear(proj_dim, proj_dim), 
                                       nn.BatchNorm1d(proj_dim), 
                                       nn.ReLU(), 
                                       nn.Linear(proj_dim, proj_dim))
        
        self.predictor = nn.Sequential(nn.Linear(proj_dim, proj_dim), 
                                       nn.BatchNorm1d(proj_dim), 
                                       nn.ReLU(), 
                                       nn.Linear(proj_dim, proj_dim))

    def decode(self, obs, act):
        n, t, d = obs.shape
        obs = self.obs_in(obs)
        act = self.act_in(act)
        
        # mlr: predict [obs] from a [obs] token
        # clt: predict [obs] from a [act] token 
        obs = self.dec_norm(obs)
        x = self.decoder(obs, act, dataset_type='demonstration')
        obs = x[:, torch.arange(t) * 2, :]
        
        return obs

    def act_predict(self, x1, x2):
        x = torch.cat((x1, x2), -1)
        x = self.act_predictor(x)
        return x

    def project(self, x):
        n, t, d = x.shape
        x = rearrange(x, 'n t d-> (n t) d')
        if d != self.proj_dim:
            x = self.obs_in(x)
            x = self.dec_norm(x)
        
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
