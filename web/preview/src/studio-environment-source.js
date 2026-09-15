// Canonical studio lighting, preserved from VehiclePreview.createEnvironment.
// Used by tools/bake_preview_environment.cjs; never convolved on the phone.
export function createStudioEnvironmentScene(THREE) {
 const env=new THREE.Scene();env.background=new THREE.Color(.055,.065,.085);
 const card=(pos,w,h,color)=>{const material=new THREE.MeshBasicMaterial({color:new THREE.Color(...color),side:THREE.DoubleSide,toneMapped:false});const panel=new THREE.Mesh(new THREE.PlaneGeometry(w,h),material);panel.position.set(...pos);panel.lookAt(0,.5,0);env.add(panel);};
 card([0,5,-1],7,1.3,[4.5,4.8,5.2]);card([-4,2,0],7,1.8,[2.8,3.4,4]);card([4,2.5,1],7,1.0,[3.8,4.0,4.2]);card([0,3,5],4,2,[1.2,1.7,2.2]);
 return env;
}
