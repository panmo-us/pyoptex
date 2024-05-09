import numpy as np

from .formulas import detect_block_end_from_start, remove_update_vinv
from .simulation import State
from ..utils.design import force_Zi_asc
from ..._profile import profile


def groups_remove(Yn, Zs, pos, colstart):
    """
    Computes the change in groups when removing run at `pos`.

    Parameters
    ----------
    Yn : np.array(2d)
        The design matrix.
    Zs : list(np.array(1d) or None)
        The grouping matrices.
    pos : int
        The run to remove.
    colstart : np.array(1d)
        The start column of each factor.

    Returns
    -------
    b : list(tuple(start, end, group_from, group_to))
        Each element represents a factor random effect and specifies
        whether runs from this factor should be moved to another group.
    """
    # Initialization
    b = [() for _ in range(len(Zs))]

    # Loop over all factors
    for i in range(colstart.size - 1):
        # Check if it is a grouped column
        if Zs[i] is not None:
            # Loop initialization
            Zi = Zs[i]
            cols = slice(colstart[i], colstart[i+1])
            
            # Detect double split
            if pos > 0 and pos < len(Zi) - 1 \
                        and np.all(Yn[pos-1, cols] == Yn[pos, cols]) \
                        and Zi[pos-1] != Zi[pos+1]:
                block_end = detect_block_end_from_start(Zi, pos+1)
                b[i] = (pos, block_end-1, Zi[pos+1], Zi[pos-1])

    return b

###################################################

@profile
def remove_optimal_onebyone(state, params):
    """
    Removes runs from the design until within the cost constraints. Runs
    are selected and removed one-by-one for minimal metric loss and 
    maximal cost reduction.

    Parameters
    ----------
    state : :py:class:`State <cost_optimal_designs.simulation.State>`
        The state from which to remove.
    params : :py:class:`Parameters <cost_optimal_designs.simulation.Parameters>`
        The simulation parameters.

    Returns
    -------
    new_state : :py:class:`State <cost_optimal_designs.simulation.State>`
        The new state with runs removed.
    """
    nprior = len(params.prior)

    # Temporary variables
    metrics = np.zeros(len(state.Y), dtype=np.float64)
    keep = np.ones(len(state.Y), dtype=np.bool_)

    # Find which to drop
    while np.any(state.cost_Y > state.max_cost):

        # Loop initialization
        best_metric = np.inf
        best_state = state

        # Compute bottleneck indices
        idx = np.unique(np.concatenate([idx for _, _, idx in state.costs]))
        idx = idx[idx >= nprior]

        # Loop over all available runs
        for k in idx:
        # for k in range(nprior, len(state.Y)):
            # Set keep to false
            keep[k] = False

            # Define new design
            Yn = state.Y[keep[:len(state.Y)]]
            Xn = state.X[keep[:len(state.Y)]]

            # Compute Zsn and Vinvn
            if any(Zi is not None for Zi in state.Zs):
                b = groups_remove(Yn, state.Zs, k, params.colstart)
                Zsn, Vinvn = remove_update_vinv(state.Vinv, state.Zs, k, b, params.ratios)
                Zsn = tuple(force_Zi_asc(Zi) if Zi is not None else None for Zi in Zsn)
            else:
                # Shortcut as there are no hard-to-vary factors
                Zsn = state.Zs
                Vinvn = np.broadcast_to(np.eye(len(Yn)), (state.Vinv.shape[0], len(Yn), len(Yn)))

            # Compute cost reduction
            costsn = params.fn.cost(Yn)
            cost_Yn = np.array([np.sum(c) for c, _, _ in costsn])
            max_cost = np.array([m for _, m, _ in costsn])

            # Compute new metric
            metricn = params.fn.metric.call(Yn, Xn, Zsn, Vinvn, costsn)

            # Create new state
            staten = State(Yn, Xn, Zsn, Vinvn, metricn, cost_Yn, costsn, max_cost)
                
            # Compute metric loss per cost
            mt = np.sum(state.cost_Y / state.max_cost * np.array([c.size for c, _, _ in state.costs])) / len(state.Y) \
                - np.sum(staten.cost_Y / staten.max_cost * np.array([c.size for c, _, _ in staten.costs])) / len(staten.Y)
            metric_temp = (state.metric - staten.metric) / (mt / len(state.costs))

            # Minimize
            if metric_temp < best_metric or np.isinf(best_metric):
                best_metric = metric_temp
                best_state = staten
            
            # Set keep to true
            keep[k] = True

        # Drop the run
        state = best_state

    return state

    
