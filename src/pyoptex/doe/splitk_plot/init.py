import numpy as np
import numba
from numba.typed import List

from ..utils.design import encode_design
from ...utils.numba import numba_all_axis1

@numba.njit
def __init_unconstrained(effect_types, effect_levels, grps, thetas, coords, Y, complete=False):
    """
    This function is created to avoid possible recursion. Numba has issues with it.

    .. note::
        See :py:func:`initialize_single` for more information

    .. note::
        This function is Numba accelerated

    """
    ##################################################
    # UNCONSTRAINED DESIGN
    ##################################################
    # Loop over all columns
    for col in range(effect_types.size):
        # Extract parameters
        level = effect_levels[col]
        typ = effect_types[col]

        # Generate random values
        lgrps = grps[col]
        n = len(lgrps)
        size = thetas[level]

        if complete:
            if typ == 1:
                # Continuous factor
                r = np.random.rand(n) * 2 - 1
            else:
                # Discrete factor
                choices = np.arange(typ, dtype=np.float64)
                if typ >= n:
                    r = np.random.choice(choices, n, replace=False)
                else:
                    n_replicates = n // choices.size
                    r = np.random.permutation(np.concatenate((np.repeat(choices, n_replicates), np.random.choice(choices, n - choices.size * n_replicates))))
        else:
            # Extract the possible coordinates
            if typ > 1:
                # Convert to decoded values for categorical factors
                choices = np.arange(len(coords[col]), dtype=np.float64)
            else:
                choices = coords[col].flatten()

            # Pick from the choices and try to have all of them atleast once
            if choices.size >= n:
                r = np.random.choice(choices, n, replace=False)
            else:
                n_replicates = n // choices.size
                r = np.random.permutation(np.concatenate((np.repeat(choices, n_replicates), np.random.choice(choices, n - choices.size * n_replicates))))
        
        # Fill design
        for i, grp in enumerate(lgrps):
            Y[grp*size: (grp+1)*size, col] = r[i]

    return Y

@numba.njit
def __correct_constraints(effect_types, effect_levels, grps, thetas, coords, plot_sizes, constraints, Y, complete=False):
    # Check which runs are invalid
    invalid_run = constraints(Y)

    # Store aggregated values of invalid run per level
    level_all_invalid = [invalid_run]
    for i in range(plot_sizes.size - 1):
        all_invalid = numba_all_axis1(level_all_invalid[i].reshape(-1, plot_sizes[i]))
        level_all_invalid.append(all_invalid)

    ##################################################
    # LEVEL SELECTION
    ##################################################
    # Loop over all levels
    for level, all_invalid in zip(range(plot_sizes.size - 1, -1, -1), level_all_invalid[::-1]):
        # Define the jump
        jmp = thetas[level]

        ##################################################
        # SELECT ENTIRELY INVALID BLOCKS
        ##################################################
        # Loop over all groups in the level
        for grp in np.where(all_invalid)[0]:
            # Specify which groups to update
            grps_ = [
                np.array([g for g in grps[col] if g >= grp*jmp/thetas[l] and g < (grp+1)*jmp/thetas[l]], dtype=np.int64) 
                if l < level else (
                    np.arange(grp, grp+1, dtype=np.int64) if (l == level and grp in grps[col])
                    else np.arange(0, dtype=np.int64)
                )
                for col, l in enumerate(effect_levels)
            ]
            grps_ = List(grps_)

            ##################################################
            # REGENERATE BLOCK
            ##################################################
            # Loop until no longer all invalid
            while all_invalid[grp]:
                # Adjust the design
                Y = __init_unconstrained(effect_types, effect_levels, grps, thetas, coords, Y, complete)
                # Validate the constraints
                c = constraints(Y[grp*jmp:(grp+1)*jmp])
                # Update all invalid
                for l in range(level):
                    level_all_invalid[l][grp*int(jmp/thetas[l]):(grp+1)*int(jmp/thetas[l])] = c
                    c = numba_all_axis1(c.reshape(-1, plot_sizes[l]))
                all_invalid[grp] = c[0]

    return Y

def initialize_feasible(params, complete=False, max_tries=10):
    """
    Generate a random initial design for split^k plot problem.
    `grps` specifies at each level which level-groups should be
    initialized. This is useful when augmenting an existing design.

    Parameters
    ----------

    Returns
    -------

    """
    # Compute design sizes
    n = np.prod(params.plot_sizes)
    ncol = params.effect_types.shape[0]

    # Initiate design matrix
    Y = params.prior
    if Y is None:
        Y = np.zeros((n, ncol), dtype=np.float64)

    feasible = False
    tries = 0
    while not feasible:
        # Add one try
        tries += 1

        # Initialize unconstrained
        Y = __init_unconstrained(
            params.effect_types, params.effect_levels, params.grps, 
            params.thetas, params.coords, Y, complete
        )

        # Constraint corrections
        Y = __correct_constraints(
            params.effect_types, params.effect_levels, params.grps, 
            params.thetas, params.coords, params.plot_sizes, params.fn.constraints,
            Y, complete
        )

        # Make sure it's feasible
        Yenc = encode_design(Y, params.effect_types)
        Xenc = params.Y2X(Yenc)
        feasible = np.linalg.matrix_rank(Xenc) == Xenc.shape[1]

        # Check if not in infinite loop
        if tries >= max_tries and not feasible:
            raise ValueError('Unable to find a feasible design the constraints')
                    
    return Y, (Yenc, Xenc)

