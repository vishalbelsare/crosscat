#
#   Copyright (c) 2010-2013, MIT Probabilistic Computing Project
#
#   Lead Developers: Dan Lovell and Jay Baxter
#   Authors: Dan Lovell, Baxter Eaves, Jay Baxter, Vikash Mansinghka
#   Research Leads: Vikash Mansinghka, Patrick Shafto
#
#   Licensed under the Apache License, Version 2.0 (the "License");
#   you may not use this file except in compliance with the License.
#   You may obtain a copy of the License at
#
#       http://www.apache.org/licenses/LICENSE-2.0
#
#   Unless required by applicable law or agreed to in writing, software
#   distributed under the License is distributed on an "AS IS" BASIS,
#   WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
#   See the License for the specific language governing permissions and
#   limitations under the License.
#

import crosscat.cython_code.State as State
import crosscat.utils.sample_utils as su
import crosscat.utils.data_utils as du

import crosscat.tests.component_model_extensions.ContinuousComponentModel as ccmext
import crosscat.tests.component_model_extensions.MultinomialComponentModel as mcmext

import random
import pylab
import numpy

import unittest

from scipy import stats

default_data_parameters = dict(
    symmetric_dirichlet_discrete=dict(weights=[1.0/5.0]*5),
    normal_inverse_gamma=dict(mu=0.0, rho=1.0)
    )

is_discrete = dict(
    symmetric_dirichlet_discrete=True,
    normal_inverse_gamma=False
    )


def main():
    print " "
    print "======================================================================="
    print "TEST SINGLE COMPONENT INFERENCE QUALITY"
    print " Performs a 2-sample KS or Chi-square test for a single column"
    print " problem with a single cluster"
    print " "
    print " ** NOTE: Used primarily for testing new data types."
    unittest.main()

class TestComponentModelQuality(unittest.TestCase):
    def setUp(self):
        self.show_plot = False

    def test_normal_inverse_gamma_model(self):
        assert(test_one_feature_sampler(ccmext.p_ContinuousComponentModel, 
            show_plot=self.show_plot) > .1)

    def test_dirchlet_multinomial_model(self):
        assert(test_one_feature_sampler(mcmext.p_MultinomialComponentModel, 
            show_plot=self.show_plot) > .1)


def get_params_string(params):
    string = dict()
    for k,v in params.iteritems():
        if isinstance(v, float):
            string[k] = round(v,3)
        elif isinstance(v, list):
            string[k] = [round(val,3) for val in v]

    return str(string)

def cdf_array(X, component_model):
    cdf = numpy.zeros(len(X))
    for i in range(len(X)):
        x = X[i]
        cdf[i] = component_model.get_predictive_cdf(x,[])

    assert i == len(X)-1
    assert i > 0
    return cdf

def test_one_feature_sampler(component_model_type, num_rows=100, show_plot=False, print_out=True):
    """
    Tests the ability of component model of component_model_type to capture the
    distribution of the data.
    1. Draws 100 random points from a standard normal distribution
    2. Initializes a component model with that data (and random hyperparameters)
    3. Draws data from that component model
    4. Initialize a crosscat state with that data
    5. Get one sample after 100 transitions
    6. Draw predictive samples
    7. Caluclates the 95 precent support of the continuous distribution or the 
        entire support of the discrete distribution
    8. Calculate the true pdf for each point in the support
    9. Calculate the predictive probability given the sample for each point in
        the support
    10. (OPTIONAL) Plot the original data, predictive samples, pdf, and 
        predictive probabilities 
    11. Calculate goodness of fit stats (returns p value)
    """
    N = num_rows
    
    get_next_seed = lambda : random.randrange(2147483647)

    data_params = default_data_parameters[component_model_type.model_type]
    
    X = component_model_type.generate_data_from_parameters(data_params, N, gen_seed=get_next_seed())
    
    hyperparameters = component_model_type.draw_hyperparameters(X)[0]
    
    component_model = component_model_type.from_data(X, hyperparameters)
    
    model_parameters = component_model.sample_parameters_given_hyper()
    
    # generate data from the parameters
    T = component_model_type.generate_data_from_parameters(model_parameters, N, gen_seed=get_next_seed())

    # create a crosscat state 
    M_c = du.gen_M_c_from_T(T, cctypes=[component_model_type.cctype])
    
    state = State.p_State(M_c, T)
    
    # transitions
    n_transitions = 100
    state.transition(n_steps=n_transitions)
    
    # get the sample
    X_L = state.get_X_L()
    X_D = state.get_X_D()
    
    # generate samples
    # kstest has doesn't compute the same answer with row and column vectors
    # so we flatten this column vector into a row vector.
    predictive_samples = numpy.array(su.simple_predictive_sample(M_c, X_L, X_D, [], [(N,0)], get_next_seed, n=N)).flatten(1)
    
    # get support
    discrete_support = component_model_type.generate_discrete_support(model_parameters)

    # calculate simple predictive probability for each point
    Q = [(N,0,x) for x in discrete_support]

    probabilities = su.simple_predictive_probability(M_c, X_L, X_D, []*len(Q), Q,)
    
    T = numpy.array(T)

    # get histogram. Different behavior for discrete and continuous types. For some reason
    # the normed property isn't normalizing the multinomial histogram to 1.
    if is_discrete[component_model_type.model_type]:
        T_hist, edges = numpy.histogram(T, bins=len(discrete_support))
        S_hist, _ =  numpy.histogram(predictive_samples, bins=edges)
        T_hist = T_hist/float(numpy.sum(T_hist))
        S_hist = S_hist/float(numpy.sum(S_hist))
        edges = numpy.array(discrete_support,dtype=float)
    else:
        T_hist, edges = numpy.histogram(T, bins=min(20,len(discrete_support)), normed=True)
        S_hist, _ =  numpy.histogram(predictive_samples, bins=edges, normed=True)
        edges = edges[0:-1]

    # Goodness-of-fit-tests
    if not is_discrete[component_model_type.model_type]:
        # do a KS tests if the distribution in continuous
        cdf = lambda x: component_model_type.cdf(x, model_parameters)
        # stat, p = stats.kstest(predictive_samples, cdf)   # 1-sample test
        stat, p = stats.ks_2samp(predictive_samples, T[:,0]) # 2-sample test
        test_str = "2-sample KS"
    else:
        # Cressie-Read power divergence statistic and goodness of fit test.
        # This function gives a lot of flexibility in the method <lambda_> used.
        freq_obs = S_hist*N
        freq_exp = numpy.exp(probabilities)*N
        stat, p = stats.power_divergence(freq_obs, freq_exp, lambda_='pearson')
        test_str = "Chi-square"
    
    if show_plot:
        pylab.axes([0.1, 0.1, .8, .7])
        # bin widths
        width = (numpy.max(edges)-numpy.min(edges))/len(edges)
        pylab.bar(edges, T_hist, color='blue', alpha=.5, width=width, label='Original data')
        pylab.bar(edges, S_hist, color='red', alpha=.5, width=width, label='Predictive samples')

        # plot actual pdf of support given data params
        pylab.scatter(discrete_support, 
            numpy.exp(component_model_type.log_pdf(numpy.array(discrete_support), 
            model_parameters)), 
            c="blue", 
            s=100, 
            label="true pdf", 
            alpha=1)
                
        # plot predictive probability of support points
        pylab.scatter(discrete_support, 
            numpy.exp(probabilities), 
            c="red", 
            s=100, 
            label="predictive probability", 
            alpha=1)
            
        pylab.legend()

        ylimits = pylab.gca().get_ylim()
        pylab.ylim([0,ylimits[1]])

        title_string = "%i samples drawn from %s w/ params: \n%s\ninference after %i crosscat transitions\n%s test: p = %f" \
            % (N, component_model_type.cctype, str(get_params_string(model_parameters)), n_transitions, test_str, round(p,4))

        pylab.title(title_string, fontsize=12)

        pylab.show()

    if print_out:
        print "======================================"
        print "IMPUTE SINGLE CLUSTER INFERNCE QUALITY"
        print "TEST INFORMATION:"
        print "       data type: " + component_model_type.cctype
        print "        num_rows: " + str(num_rows)
        print " num_transitions:" + str(n_transitions)
        print "RESULTS (%s) for each chain" % test_str 
        print "   statistic(s): " + str(stat)
        print "           p(s): " + str(p)

    return p

if __name__ == '__main__':
    main()