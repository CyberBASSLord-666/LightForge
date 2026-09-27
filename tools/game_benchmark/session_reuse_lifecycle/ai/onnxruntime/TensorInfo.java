package ai.onnxruntime;
public final class TensorInfo {
    public final OnnxJavaType type;private final long[] shape;
    TensorInfo(OnnxJavaType type,long[] shape){this.type=type;this.shape=shape.clone();}
    public long[] getShape(){return shape.clone();}
}
