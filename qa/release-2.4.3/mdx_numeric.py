"""Units-correct, fixed MDX parity criteria (reviewed before the qualifying run).

The first exploratory comparison incorrectly applied a normalized-waveform
absolute bound to raw FFT coefficients. That failed result is retained under
initial-mdx-absolute-only/. The qualifying criteria check every spectral
coefficient with a fixed absolute+relative tolerance, plus spectral RMS error,
and enforce stricter absolute bounds on the normalized decoded audio.
"""
import numpy as np
SPECTRUM_THRESHOLDS={'absolute_tolerance':1e-4,'relative_tolerance':1e-5,'rmse':1e-5,'relative_rmse':1e-3}
WAVEFORM_THRESHOLDS={'max_absolute_error':1e-6,'rmse':1e-7,'relative_rmse':1e-4}

def compare(native, reference, kind):
    if kind not in {'positive','negative','waveform'}:raise ValueError('Unknown output kind')
    native=np.asarray(native,dtype=np.float64);reference=np.asarray(reference,dtype=np.float64)
    if native.shape!=reference.shape or native.ndim!=1 or not native.size:raise ValueError('Incomplete output')
    if not np.all(np.isfinite(native)) or not np.all(np.isfinite(reference)):raise ValueError('Nonfinite output')
    delta=native-reference;absolute=np.abs(delta);rmse=float(np.sqrt(np.mean(delta*delta)));rms=float(np.sqrt(np.mean(reference*reference)))
    result={'output':kind,'samples':int(native.size),'finite':True,'max_absolute_error':float(np.max(absolute)),'rmse':rmse,'reference_rms':rms,'relative_rmse':rmse/max(1e-12,rms),'identical':not np.any(delta)}
    if kind=='waveform':result['within_thresholds']=all(result[k]<=v for k,v in WAVEFORM_THRESHOLDS.items())
    else:
        tolerance=SPECTRUM_THRESHOLDS['absolute_tolerance']+SPECTRUM_THRESHOLDS['relative_tolerance']*np.abs(reference)
        result['coefficient_violations']=int(np.count_nonzero(absolute>tolerance))
        result['maximum_scaled_error']=float(np.max(absolute/tolerance))
        result['within_thresholds']=result['coefficient_violations']==0 and result['rmse']<=SPECTRUM_THRESHOLDS['rmse'] and result['relative_rmse']<=SPECTRUM_THRESHOLDS['relative_rmse']
    return result
