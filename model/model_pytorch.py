import torch
import torch.optim as optim
import torch.nn as nn
import torch.nn.functional as F
import os
import numpy as np
import sys
from torch.autograd import Variable

IMG_H, IMG_W, IMG_C = (22,10,1)

EXP_PATH = './pytorch_model/'

n_actions = 7

def convOutShape(shape_in,kernel_size,stride):
    return ((shape_in[0] - kernel_size) // stride + 1, (shape_in[1] - kernel_size) // stride + 1 )

class Net(torch.jit.ScriptModule):

    def __init__(self):
        super(Net,self).__init__()
        
        kernel_size = 3
        stride = 1
        filters = 32
        self.conv1 = nn.Conv2d(1, filters, kernel_size, stride)
        self.bn1 = nn.BatchNorm2d(filters)
        _shape = convOutShape((22,10), kernel_size, stride)
        self.conv2 = nn.Conv2d(filters, filters, kernel_size, stride)
        self.bn2 = nn.BatchNorm2d(filters)
        _shape = convOutShape(_shape, kernel_size, stride)
       
        flat_in = _shape[0] * _shape[1] * filters

        n_fc1 = 128
        self.fc1 = nn.Linear(flat_in, n_fc1)
        
        flat_out = n_fc1
 
        self.fc_p = nn.Linear(flat_out, n_actions)
        self.fc_v = nn.Linear(flat_out, 1)
        self.fc_var = nn.Linear(flat_out, 1)


    @torch.jit.script_method
    def forward(self, x):
        x = self.bn1(F.relu(self.conv1(x)))
        x = self.bn2(F.relu(self.conv2(x)))
        x = x.view(-1, 3456)

        x = F.relu(self.fc1(x))        

        policy = F.softmax(self.fc_p(x), dim=1)
        value = self.fc_v(x)
        var = self.fc_var(x)
        return value, var, policy

def convert(x):
    return torch.from_numpy(x.astype(np.float32))

class Model:
    def __init__(self,new=True):

        self.model = Net()
        self.optimizer = optim.Adam(self.model.parameters(), lr=1e-4)
        self.scheduler = None

        self.v_mean = 0
        self.v_std = 1

        self.var_mean = 3
        self.var_std = 1

    def _loss(self,batch):

        state = convert(batch[0])
        value = convert(batch[1])
        variance = convert(batch[2])
        policy = convert(batch[3])

        _v, _var, _p = self.model(state)

        loss_v = F.mse_loss(_v, value)
        loss_var = F.mse_loss(_var, variance)
        #loss_v = Variable(torch.FloatTensor([0]))
        #loss_p = F.kl_div(torch.log(_p),policy)
        loss_p = Variable(torch.FloatTensor([0]))

        loss = loss_v + loss_var + loss_p
        return loss, loss_v, loss_var, loss_p

    def compute_loss(self,batch):

        self.model.eval()

        losses = self._loss(batch)
        
        result = [l.data.numpy() for l in losses]

        return result

    def train(self,batch):

        self.model.train()

        self.optimizer.zero_grad()

        losses = self._loss(batch)

        losses[0].backward()

        self.optimizer.step()

        result = [l.data.numpy() for l in losses]

        return result

    def inference(self,batch):

        self.model.eval()

        state = convert(batch)
        
        with torch.no_grad():
            output = self.model(state)

        result = [o.data.numpy() for o in output]
        result[0] = result[0] * self.v_std + self.v_mean
        result[1] = result[1] * self.var_std + self.var_mean

        return result

    def update_scheduler(self,val_loss):

        if self.scheduler:
            self.scheduler.step(val_loss)

    def save(self):

        sys.stdout.write('Saving model...\n')
        sys.stdout.flush()

        if not os.path.isdir(EXP_PATH):
            sys.stdout.write('Export path does not exist, creating a new one...\n')
            sys.stdout.flush()
            os.mkdir(EXP_PATH)

        filename = EXP_PATH + 'model_checkpoint'

        full_state = {
                    'model_state_dict': self.model.state_dict(),
                    'optimizer_state_dict': self.optimizer.state_dict(),
                    'v_mean': self.v_mean,
                    'v_std': self.v_std,
                    'var_mean': self.var_mean,
                    'var_std': self.var_std,
                }

        torch.save(full_state, filename)

    def load(self):

        filename = EXP_PATH + 'model_checkpoint'

        if os.path.isfile(filename):
            sys.stdout.write('Loading model...\n')
            sys.stdout.flush()
            checkpoint = torch.load(filename)
            self.model.load_state_dict(checkpoint['model_state_dict'])
            self.optimizer.load_state_dict(checkpoint['optimizer_state_dict'])
            self.v_mean = checkpoint['v_mean'] 
            self.v_std = checkpoint['v_std'] 
            self.var_mean = checkpoint['var_mean'] 
            self.var_std = checkpoint['var_std'] 
        else:
            sys.stdout.write('Checkpoint not found, using default model\n')
            sys.stdout.flush()
