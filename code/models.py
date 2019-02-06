"""Define pytorch models."""
from collections import OrderedDict
import torch
import torch.nn as nn
from torch import Tensor
from abstract import ParametricFunction, Tensorable, Shape
from convert import check_tensor
# from mylog import log
# from uuid import uuid4

class MLP(nn.Module, ParametricFunction):
    """MLP"""
    def __init__(self, nb_inputs: int, nb_outputs: int,
                 nb_layers: int, hidden_size: int) -> None:
        super().__init__()
        self._nb_inputs = nb_inputs
        self._nb_outputs = nb_outputs
        modules = [('fc0', nn.Linear(nb_inputs, hidden_size)), # type: ignore
                   ('ln0', nn.LayerNorm(hidden_size)),
                   ('relu0', nn.ReLU())]
        sub_core = [[(f'fc{i+1}', nn.Linear(hidden_size, hidden_size)),
                     (f'ln{i+1}', nn.LayerNorm(hidden_size)),
                     (f'relu{i+1}', nn.ReLU())] for i in range(nb_layers)]
        modules += [mod for mods in sub_core for mod in mods]
        last_layer = nn.Linear(hidden_size, nb_outputs)
        last_layer.bias.data.zero_()
        modules += [(f'fc{nb_layers+1}', last_layer)]
        self._core = nn.Sequential(OrderedDict(modules))

    def forward(self, *inputs: Tensorable):
        device = next(self.parameters())
        return self._core(check_tensor(inputs[0], device))

    def input_shape(self) -> Shape:
        return ((self._nb_inputs,),)

    def output_shape(self) -> Shape:
        return ((self._nb_outputs,),)

class ContinuousPolicyMLP(MLP, ParametricFunction):
    """MLP with a Tanh on top..."""
    def forward(self, *inputs: Tensorable):
        return torch.tanh(super().forward(*inputs))

class ContinuousAdvantageMLP(MLP, ParametricFunction):
    """MLP with 2 inputs, 1 output."""
    def __init__(self, nb_state_feats: int, nb_actions: int,
                 nb_layers: int, hidden_size: int, nb_outputs: int) -> None:
        super().__init__(nb_state_feats + nb_actions, nb_outputs,
                         nb_layers, hidden_size)
        self._nb_state_feats = nb_state_feats
        self._nb_actions = nb_actions

    def forward(self, *inputs: Tensorable):
        device = next(self.parameters())
        return super().forward(torch.cat(
            [
                check_tensor(inputs[0], device),
                check_tensor(inputs[1], device)],
            dim=-1))

    def input_shape(self) -> Shape:
        return ((self._nb_state_feats,), (self._nb_actions,))

    def output_shape(self) -> Shape:
        return ((self._nb_outputs,),)

class CustomBN(nn.Module):
    def __init__(self, nb_feats: int, eps: float = 1e-5) -> None:
        super().__init__()
        self._eps = eps
        self.register_buffer('_count', torch.zeros(1, requires_grad=False))
        self.register_buffer('_mean', torch.zeros(nb_feats, requires_grad=False))
        self.register_buffer('_squared_mean', torch.ones(nb_feats, requires_grad=False))

        # debug: we are going to log _count, _mean and _squared_mean
        # self._prefix = 'stats/' + str(uuid4())

    def forward(self, *inputs: Tensorable) -> torch.Tensor:
        device = self._mean.device # type: ignore
        t_input = check_tensor(inputs[0], device)
        batch_size = t_input.size(0)

        # log
        # count = int(self._count.item())
        # if (count // batch_size) % 100 == 99:
        #     log(self._prefix + 'count', count, count)
        #     log(self._prefix + 'min_mean', self._mean.abs().min(), count) # type: ignore
        #     log(self._prefix + 'max_mean', self._mean.abs().max(), count) # type: ignore
        #     log(self._prefix + 'min_sq_mean', self._squared_mean.min(), count) # type: ignore
        #     log(self._prefix + 'max_sq_mean', self._squared_mean.max(), count) # type: ignore
        std = torch.sqrt(torch.clamp(self._squared_mean - self._mean ** 2, min=1e-2)) # type: ignore
        output = (t_input - self._mean) / std # type: ignore
        with torch.no_grad():
            self._mean = (self._mean * self._count + batch_size * t_input.mean(dim=0)) / (self._count + batch_size) # type: ignore
            self._squared_mean = (self._squared_mean * self._count + batch_size * (t_input ** 2).mean(dim=0)) / (self._count + batch_size) # type: ignore
            self._count += batch_size
        return output

class NormalizedMLP(nn.Module, ParametricFunction):
    def __init__(self, model: ParametricFunction) -> None:
        super().__init__()
        self._model = model
        # only normalize first input (is this what we want to do in the long go?)
        self._bn = CustomBN(self._model.input_shape()[0][0])

    def forward(self, *inputs: Tensorable):
        device = next(self.parameters())
        tens_inputs = [check_tensor(inp, device) for inp in inputs]
        tens_inputs = [self._bn(tens_inputs[0])] + tens_inputs[1:]
        return self._model(*tens_inputs)

    def input_shape(self) -> Shape:
        return self._model.input_shape()

    def output_shape(self) -> Shape:
        return self._model.output_shape()


class DiscreteRandomPolicy(nn.Module, ParametricFunction):
    def __init__(self, nb_state_feats: int, nb_actions: int,
                 nb_layers:int, hidden_size:int) -> None:
        nn.Module.__init__(self)
        self._model = MLP(nb_state_feats, nb_actions, nb_layers, hidden_size)

    def forward(self, *inputs: Tensorable) -> Tensor:
        x = self._model(inputs[0])
        return x

    def input_shape(self) -> Shape:
        return self._model.input_shape()

    def output_shape(self) -> Shape:
        return self._model.output_shape()


class ContinuousRandomPolicy(nn.Module, ParametricFunction):
    def __init__(self, nb_state_feats: int, nb_actions: int,
                 nb_layers: int, hidden_size: int) -> None:
        nn.Module.__init__(self)
        self._model = MLP(nb_state_feats, hidden_size, nb_layers-1, hidden_size)
        self.ln = nn.LayerNorm(hidden_size)
        self.relu = nn.ReLU()
        self._fc_mu = nn.Linear(hidden_size, nb_actions)
        self._fc_sigma = nn.Linear(hidden_size, nb_actions)


    def forward(self, *inputs: Tensorable) -> Tensor:
        x = self._model(inputs[0])
        x = self.relu(self.ln(x))
        mu = torch.tanh(self._fc_mu(x))
        sigma = torch.log(1 + torch.exp(self._fc_sigma(x)))
        return mu, sigma

    def input_shape(self) -> Shape:
        return self._model.input_shape()

    def output_shape(self) -> Shape:
        return ((self._nb_actions,), (self._nb_actions,))















