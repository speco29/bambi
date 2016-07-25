from abc import ABCMeta, abstractmethod
from six import string_types
import numpy as np
import warnings
from bambi.priors import default_priors
try:
    import pymc3 as pm
except:
    warnings.warn("PyMC3 could not be imported. You will not be able to use "
                  "PyMC3 as the back-end for your models.")


class BackEnd(object):

    __metaclass__ = ABCMeta

    @abstractmethod
    def build(self):
        pass

    @abstractmethod
    def run(self):
        pass


class PyMC3BackEnd(BackEnd):

    def __init__(self):
        self.reset()

    def reset(self):
        self.model = pm.Model()
        self.mu = 0.
        self.dists = {}
        self.shared_params = {}

    def _build_dist(self, label, dist, **kwargs):
        ''' Build and return a PyMC3 Distribution. '''
        if isinstance(dist, string_types):
            if not hasattr(pm, dist):
                raise ValueError("The Distribution class '%s' was not "
                                 "found in PyMC3." % dist)
            dist = getattr(pm, dist)
        return dist(label, **kwargs)

    def build(self, model, reset=True):

        if reset:
            self.reset()

        with self.model:

            for t in model.terms.values():

                n_cols = t.values.shape[1]
                label = t.label
                dist_name = t.prior['name']
                dist_args = t.prior['args']

                # Random effects
                if t.random:

                    # User can pass sigma specification in sigma_kws.
                    # If not provided, default to HalfCauchy with beta = 10.
                    try:
                        sigma_dist_name = t.prior['sigma']['name']
                        sigma_dist_args = t.prior['sigma']['args']
                    except:
                        sigma_dist_name = 'HalfCauchy'
                        sigma_dist_args = {'beta': 10}
                        
                    if t.split_by is None:
                        sigma = self._build_dist('sigma_' + label, sigma_dist_name,
                                                 **sigma_dist_args)
                        dist_args['sd'] = sigma
                        u = self._build_dist('u_' + label, dist_name,
                                             shape=n_cols, **dist_args)
                        self.mu += pm.dot(t.values, u)
                    else:
                        for i in range(t.values.shape[-1]):
                            # select just the factor levels that appear with the
                            # current level of split_by
                            group_items = t.values[:, :, i].any(0)
                            selected = t.values[:, group_items, i]
                            # add the level effects to the model
                            name = '%s_%s' % (label, t.split_by.levels[i])
                            sigma = self._build_dist('sigma_' + name, sigma_dist_name,
                                                     **sigma_dist_args)
                            name, size = 'u_' + name, selected.shape[1]
                            u = self._build_dist(name, dist_name, shape=size, **dist_args)
                            self.mu += pm.dot(selected, u)[:, None]

                # Fixed effects
                else:
                    b = self._build_dist('b_' + label, dist_name,
                                         shape=t.values.shape[-1], **dist_args)
                    if t.split_by is not None:
                        t.values = np.squeeze(t.values)
                    self.mu += pm.dot(t.values, b)[:, None]

            # TODO: accept sigma params as an argument
            sigma_params = default_priors['sigma']
            sigma = self._build_dist('sigma', sigma_params['name'],
                                     **sigma_params['args'])
            y = model.y.values
            y_obs = pm.Normal('y_pred', mu=self.mu, sd=sigma, observed=y)

    def run(self, **kwargs):
        samples = kwargs.pop('samples', 1000)
        with self.model:
            self.trace = pm.sample(samples, **kwargs)
