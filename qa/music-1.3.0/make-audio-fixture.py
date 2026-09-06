"""Deterministic percussion/chord fixture with sample-clock beat annotation.
Not a perceptual benchmark; exercises the unchanged trained model end-to-end.
"""
from pathlib import Path
import json, math, wave
import numpy as np
rate=22050
bpm=124.5
period=60/bpm
beats=np.array([.123+i*period for i in range(96)])
duration=float(beats[-1]+1.2)
audio=np.zeros(math.ceil(duration*rate),dtype=np.float64)
rng=np.random.default_rng(130)
def add(time,values):
    start=round(time*rate)
    end=min(len(audio),start+len(values))
    audio[start:end]+=values[:end-start]
for i,time in enumerate(beats):
    t=np.arange(round(.22*rate))/rate
    pitch_phase=2*math.pi*(48*t+80*.024*(1-np.exp(-t/.024)))
    kick=.66*np.sin(pitch_phase)*np.exp(-t/.045)
    kick+=.12*rng.standard_normal(len(t))*np.exp(-t/.004)
    add(time,kick)
    if i%4 in (1,3):
        t=np.arange(round(.13*rate))/rate
        add(time,.19*rng.standard_normal(len(t))*np.exp(-t/.035)+.13*np.sin(2*math.pi*185*t)*np.exp(-t/.028))
    for half in (0,.5):
        t=np.arange(round(.045*rate))/rate
        noise=rng.standard_normal(len(t))
        high=noise-np.r_[0,noise[:-1]]
        add(time+half*period,.075*high*np.exp(-t/.008))
    if i%4==0:
        t=np.arange(round(period*3.8*rate))/rate
        root=[110,146.83,130.81,164.81][i//4%4]
        chord=sum(np.sin(2*math.pi*root*ratio*t) for ratio in (1,1.25,1.5))/3
        add(time,.09*chord*np.minimum(1,t/.04)*np.exp(-t/.8))
audio=np.clip(audio,-.98,.98)
file=Path('/tmp/lightforge-1.3.0-rhythm-fixture.wav')
with wave.open(str(file),'wb') as out:
    out.setnchannels(1);out.setsampwidth(2);out.setframerate(rate);out.writeframes((audio*32767).astype('<i2').tobytes())
Path(__file__).with_name('audio-fixture-annotations.json').write_text(json.dumps({'fixture':file.name,'sampleRate':rate,'bpm':bpm,'meter':4,'beats':beats.tolist(),'downbeats':beats[::4].tolist(),'duration':len(audio)/rate},indent=2))
print(file)
