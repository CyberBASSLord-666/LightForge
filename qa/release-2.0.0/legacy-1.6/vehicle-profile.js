/* Canonical custom-show capabilities, not a list of every electrical load.
 * Tesla's public xLights contract is cross-vehicle. Highland hardware references
 * identify assemblies; Tesla has not published a Highland per-lens FSEQ drawing.
 * Keep that distinction when presenting the preview's physical accuracy.
 */
(function(root) {
  'use strict';
  const GUIDE='https://github.com/teslamotors/light-show';
  const MANUAL='https://service.tesla.com/docs/Model3/ServiceManual/2024/en-us/';
  const sources=Object.freeze([
    {id:'tesla-show',title:'Tesla Light Show xLights Guide',url:GUIDE},
    {id:'tesla-layout',title:'Tesla xLights channel definitions',url:'https://github.com/teslamotors/light-show/blob/master/xlights/tesla_xlights_show_folder.zip'},
    {id:'highland-service',title:'Model 3 2024+ Service Manual',url:MANUAL},
    {id:'highland-headlight',title:'Highland SAE headlight assembly',url:MANUAL+'GUID-AC157E1C-9441-4687-AAD9-0CF4A69B166E.html'},
    {id:'highland-rear-fascia',title:'Highland rear fascia light assembly',url:MANUAL+'GUID-7E6EE2BC-38C5-4EEB-829E-C1020819F471.html'},
    {id:'highland-trunk-light',title:'Highland trunk lid light assembly',url:MANUAL+'GUID-D88A21D6-BA20-4743-90B8-87AE67886BD3.html'},
    {id:'highland-plate',title:'Highland license plate lights',url:MANUAL+'GUID-3723453A-1326-47E8-A7B5-59574E57DC57.html'}
  ]);
  const outputs=[];
  const light=(id,name,channels,mode,camera,note,available=true)=>outputs.push({id,name,kind:'light',channels,mode,available,camera,note,source:GUIDE+'#light-channel-mapping-details'});
  for(const [side,label,offset] of [['left','Left',0],['right','Right',1]]){
    light(side+'-outer',label+' outer beam',[1+offset],'boolean','front','On/off baseline. Tesla distinguishes reflector ramps from projector on/off, but its public guide has no Highland-specific outer-beam classification. Ramp support requires vehicle confirmation. No public matrix-pixel or image-projection addresses.');
    outputs[outputs.length-1].optionalMode='ramp';
    light(side+'-inner',label+' inner beam',[3+offset],'ramp','front','Tesla inner-beam command; supports 500, 1000 and 2000 ms transitions. Highland lens allocation is estimated in the preview.');
    light(side+'-signature',label+' signature',[5+offset],'ramp','front','White headlamp signature; supports Tesla ramp commands.');
    light(side+'-combined',label+' combined headlamp',[7+offset,9+offset,11+offset],'ramp','front','Channels 4, 5 and 6 share one output per side. Their on requests are OR combined; channel 4 selects the ramp. Highland lens allocation is estimated.');
    light(side+'-front-turn',label+' front turn signal',[13+offset],'ramp','front','Amber front turn signal within the Highland headlamp assembly.');
    light(side+'-front-fog',label+' front fog light',[15+offset],'boolean','front','No separate front fascia fog lamp is fitted to this Highland profile; this channel is unavailable.',false);
  }
  light('park-markers','Parking / side markers',[17,18,19,20],'boolean','driver','Tesla combines left/right auxiliary parking and side-marker requests. They cannot be independently sequenced on Model 3. Highland placement is estimated.');
  for(const [side,label,offset] of [['left','Left',0],['right','Right',1]]){
    light(side+'-repeater',label+' side repeater',[21+offset],'boolean','driver','Amber fender-mounted side repeater, fixed to the body rather than the mirror.');
    light(side+'-rear-turn',label+' rear turn signal',[23+offset],'boolean','rear','Rear turn-signal output; left and right have independent channels.');
  }
  light('brakes','Brake lights',[25],'boolean','rear','One command controls the brake-light group including the center high-mounted stop light; no separate left/right brake addresses.');
  light('left-tail','Left tail light',[26],'boolean','rear','Left trunk-lid tail-light assembly.');
  light('right-tail','Right tail light',[27],'boolean','rear','Right trunk-lid tail-light assembly.');
  light('reverse','Reverse lights',[28],'boolean','rear','Paired white reverse lamps in the rear fascia share this single command.');
  light('rear-fog','Rear fog lights',[29],'boolean','rear','No rear-fog output on North American Model 3; Tesla does not substitute another lamp.',false);
  light('license-plate','License plate lights',[30],'boolean','rear','The two white plate lights share one command and move with the trunk lid.');
  for(const [id,name,ch,note] of [
    ['display','Front display',176,'Full-screen RGB on the center front display only. The rear display has no documented custom-show channel.'],
    ['rgb-right-rear','Right rear ambient',179,'The right rear door accent-light segment.'],
    ['rgb-right-front','Right front ambient',182,'The right front door accent-light segment.'],
    ['rgb-dash','Dashboard ambient',185,'The center front accent-light segment across the dashboard.'],
    ['rgb-left-front','Left front ambient',188,'The left front door accent-light segment.'],
    ['rgb-left-rear','Left rear ambient',191,'The left rear door accent-light segment.']
  ]) outputs.push({id,name,kind:'rgb',channels:[ch,ch+1,ch+2],mode:'rgb',available:true,camera:'cabin',note,source:GUIDE+'#interior-rgb-lights'});
  for(const [id,name,ch,dance,limit,camera,note] of [
    ['mirrorL','Left mirror',35,false,20,'driver','Open unfolds; Close folds. Alternate these commands for choreography; Dance is unsupported.'],
    ['mirrorR','Right mirror',36,false,20,'front','Open unfolds; Close folds. Alternate these commands for choreography; Dance is unsupported.'],
    ['windowFL','Left front window',37,true,6,'driver','Open lowers the glass; Close raises it. Dance oscillates between vehicle-defined positions.'],
    ['windowRL','Left rear window',38,true,6,'driver','Open lowers the glass; Close raises it. Dance oscillates between vehicle-defined positions.'],
    ['windowFR','Right front window',39,true,6,'front','Open lowers the glass; Close raises it. Dance oscillates between vehicle-defined positions.'],
    ['windowRR','Right rear window',40,true,6,'rear','Open lowers the glass; Close raises it. Dance oscillates between vehicle-defined positions.'],
    ['trunk','Powered trunk',41,true,6,'rear','Open before Dance. Model 3 moves its trunk lid; the rear glass stays fixed.'],
    ['charge','Charge port',46,true,3,'rear','Open before Dance. Dance cycles the port LED through rainbow colors, without oscillating the door. The port auto-closes after two minutes.']
  ]) outputs.push({id,name,kind:'closure',channels:[ch],mode:'closure',available:true,camera,commands:dance?['Idle','Open','Dance','Close','Stop']:['Idle','Open','Close','Stop'],commandLimit:limit,recommendedDanceSeconds:dance?30:0,note,source:GUIDE+'#closures-channels'});
  // One JavaScript contract for planner budgets, validation and preview travel.
  // Travel is Tesla's approximate public timing, never a measured vehicle fact.
  const closureSpecifications=Object.freeze(Object.fromEntries(outputs.filter(o=>o.kind==='closure').map(o=>{
    const channel=o.channels[0],group=channel<37?'mirrors':channel<=40?'windows':channel===41?'trunk':'charge';
    return [o.id,Object.freeze({channel,group,travel:group==='trunk'?14:group==='windows'?4:2,closeTravel:group==='trunk'?4:group==='windows'?4:2,limit:o.commandLimit,home:group==='mirrors'?1:0,danceSeconds:o.recommendedDanceSeconds})];
  })));
  for(const output of outputs){Object.freeze(output.channels);if(output.commands)Object.freeze(output.commands);Object.freeze(output);}
  const profile=Object.freeze({id:'model3-highland-2025-na',version:'1.4.0',name:'2025 Model 3 Long Range RWD · North America',channels:200,
    outputs:Object.freeze(outputs),sources,closureSpecifications,
    frameIntervals:Object.freeze([15,20]),recommendedFrameInterval:20,
    lightAccuracy:'Command timing and public channel groups; Highland headlamp sub-lens allocation remains estimated.',
    movementAccuracy:'Vehicle-command simulation. Motor travel, oscillation endpoints and thermal behavior vary; positions are estimated.',
    unavailableFeatures:Object.freeze([
      'Individual matrix-headlight pixels, text and image projection',
      'Rear display color control',
      'Dome, footwell, puddle, glovebox, frunk and luggage lamps as independent show channels',
      'Motorized passenger doors, presenting door handles and powered frunk',
      'Suspension, steering, wheel rotation, seat movement and wipers'
    ]),
    scope:'Every documented custom-light-show output for this vehicle profile. Electrical features without an exposed Tesla show channel cannot be commanded by an exported FSEQ.'
  });
  if(typeof module==='object'&&module.exports)module.exports=profile;
  root.VehicleProfile=profile;
})(typeof globalThis!=='undefined'?globalThis:this);
