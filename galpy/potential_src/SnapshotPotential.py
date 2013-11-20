try: 
    from pynbody import grav_omp
except ImportError: 
    raise ImportError("This class is designed to work with pynbody snapshots -- obtain from pynbody.github.io")

from pynbody import grav_omp
import numpy as np
from Potential import Potential
import hashlib
from scipy.misc import derivative
import interpRZPotential
from scipy import interpolate 

class SnapshotPotential(Potential):
    """Create a snapshot potential object. The potential and forces are 
    calculated as needed through the _evaluate and _Rforce methods. 
    Requires an installation of [pynbody](http://pynbody.github.io).
    
    `_evaluate` and `_Rforce` calculate a hash for the array of points
    that is passed in by the user. The hash and corresponding
    potential/force arrays are stored -- if a subsequent request
    matches a previously computed hash, the previous results are
    returned and note recalculated.
    
    **Input**:
    
    *s* : a simulation snapshot loaded with pynbody

    **Optional Keywords**:
    
    *num_threads* (4): number of threads to use for calculation

    """

    def __init__(self, s, num_threads=4) : 
        self.s = s
        self._point_hash = {}
        self._amp = 1.0
    
    def __call__(self, R, z, phi = None, t = None) : 
        return self._evaluate(R,z)

    def _evaluate(self, R,z,phi=None,t=None,dR=None,dphi=None) : 
        pot, acc = self._setup_potential(R,z)
        return pot
        
    def _Rforce(self, R,z,phi=None,t=None,dR=None,dphi=None) : 
        pot, acc = self._setup_potential(R,z)
        return acc[:,0]

#    def _R2deriv(self, R,z,phi=None,t=None) : 
        

    def _setup_potential(self, R, z, use_pkdgrav = False) : 
        # cast the points into arrays for compatibility
        if isinstance(R,float) : 
            R = np.array([R])
        if isinstance(z, float) : 
            z = np.array([z])

        # compute the hash for the requested grid
        new_hash = hashlib.md5(np.array([R,z])).hexdigest()

        # if we computed for these points before, return; otherwise compute
        if new_hash in self._point_hash : 
            pot, r_acc = self._point_hash[new_hash]

#        if use_pkdgrav :
            

        else : 
            # set up the four points per R,z pair to mimic axisymmetry
            points = np.zeros((len(R),len(z),4,3))
        
            for i in xrange(len(R)) :
                for j in xrange(len(z)) : 
                    points[i,j] = [(R[i],0,z[j]),
                                   (0,R[i],z[j]),
                                   (-R[i],0,z[j]),
                                   (0,-R[i],z[j])]

            points_new = points.reshape(points.size/3,3)
            pot, acc = grav_omp.direct(self.s,points_new,num_threads=4)

            pot = pot.reshape(len(R)*len(z),4)
            acc = acc.reshape(len(R)*len(z),4,3)

            # need to average the potentials
            if len(pot) > 1:
                pot = pot.mean(axis=1)
            else : 
                pot = pot.mean()


            # get the radial accelerations
            r_acc = np.zeros((len(R)*len(z),2))
            rvecs = [(1.0,0.0,0.0),
                     (0.0,1.0,0.0),
                     (-1.0,0.0,0.0),
                     (0.0,-1.0,0.0)]
        
            # reshape the acc to make sure we have a leading index even
            # if we are only evaluating a single point, i.e. we have
            # shape = (1,4,3) not (4,3)
            acc = acc.reshape((len(r_acc),4,3))

            for i in xrange(len(R)) : 
                for j,rvec in enumerate(rvecs) : 
                    r_acc[i,0] += acc[i,j].dot(rvec)
                    r_acc[i,1] += acc[i,j,2]
            r_acc /= 4.0
            
            # store the computed values for reuse
            self._point_hash[new_hash] = [pot,r_acc]

        return pot, r_acc


class InterpSnapshotPotential(interpRZPotential.interpRZPotential) : 
    """
    Interpolated potential extracted from a simulation output. 

    
    
    """

    
    def __init__(self, s, 
                 rgrid=(0.01,2.,101), zgrid=(0.,0.2,101), 
                 enable_c = True, logR = False, zsym = True, num_threads=4) : 
        self._num_threads = num_threads
        self.s = s
        self._amp = 1.0
        
        self._interpPot = True
        self._interpRforce = True

        self._zsym = zsym
        self._enable_c = enable_c

        self._logR = logR

        # setup the grid
        self._rgrid = np.linspace(*rgrid)
        if logR : 
            self._rgrid = np.exp(self._rgrid)
            self._logrgrid = np.log(self._rgrid)

        self._zgrid = np.linspace(*zgrid)

        # calculate the grids
        self._setup_potential(self._rgrid,self._zgrid)
    
        if enable_c : 
            self._potGrid_splinecoeffs = interpRZPotential.calc_2dsplinecoeffs_c(self._potGrid)
            self._rforceGrid_splinecoeffs = interpRZPotential.calc_2dsplinecoeffs_c(self._rforceGrid)
            self._zforceGrid_splinecoeffs = interpRZPotential.calc_2dsplinecoeffs_c(self._zforceGrid)

        else :
            raise RuntimeError("InterpSnapshotPotential only works with the C interpolation routines")

    def __call__(self, R, z) : 
        return self._evaluate(R,z)

    def _setup_potential(self, R, z, use_pkdgrav = False) : 
        s = self.s
        # cast the points into arrays for compatibility
        if isinstance(R,float) : 
            R = np.array([R])
        if isinstance(z, float) : 
            z = np.array([z])


#        if use_pkdgrav :
            
        # scramble the azimuthal positions to mimic axisymmetry
        s['pos_old'] = s['pos'].copy()
        phi = np.random.uniform(-1,1,len(s))
        s['x'] = s['rxy']*np.cos(phi)
        s['y'] = s['rxy']*np.sin(phi)
    
        points = np.zeros((len(R),len(z),3))
        

        for i in xrange(len(R)) :
            for j in xrange(len(z)) : 
                points[i,j] = [R[i],0,z[j]]

        self._points = points

        points_new = points.reshape(points.size/3,3)
        pot, acc = grav_omp.direct(self.s,points_new,num_threads=self._num_threads)

        # put the particles back in their original place
        s['pos'] = s['pos_old']
        del(s['pos_old'])

        pot = pot.reshape((len(R),len(z)))
        acc = acc.reshape((len(R),len(z),3))

        r_acc = acc[:,:,0].reshape((len(R),len(z)))
        z_acc = acc[:,:,2].reshape((len(R),len(z)))
            
        # store the computed grids
        self._potGrid = pot
        self._rforceGrid = r_acc
        self._zforceGrid = z_acc

        
