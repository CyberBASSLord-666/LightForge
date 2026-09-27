package ai.onnxruntime.providers;
/** API-only control: does not create or execute a CUDA provider. */
public final class OrtCUDAProviderOptions extends ai.onnxruntime.Control.Resource {
    public OrtCUDAProviderOptions(int device){super("cudaOptions");}
    public void add(String name,String value){usable();}
}
