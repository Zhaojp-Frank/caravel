import sys

import click
import numpy as np
import pandas as pd
import tensorflow as tf
import tensorflow.contrib.slim as slim
from tensorflow.contrib.slim.nets import resnet_v1

sys.path.append("tf-models/research/slim")
from nets.mobilenet import mobilenet_v2  # isort:skip


SUPPORTED_MODELS = ["res50", "res152", "mobilenet", "mobilenet-224"]
MODELS_TO_CKPT = {
    "res50": "ckpts/resnet_v1_50.ckpt",
    "res152": "ckpts/resnet_v1_152.ckpt",
    "mobilenet": "ckpts/mobilenet_v2_1.0_96.ckpt",
    "mobilenet-224": "ckpts/mobilenet_v2_1.0_224.ckpt",
}
MODELS_TO_SHAPE = {
    "res50": [1, 224, 224, 3],
    "res152": [1, 224, 224, 3],
    "mobilenet": [1, 96, 96, 3],
    "mobilenet-224": [1, 224, 224, 3],
}


def get_input(model_name, batch_size=1):
    shape = MODELS_TO_SHAPE[model_name]
    shape[0] = batch_size
    with tf.device("/gpu:0"):
        tensor = tf.random_normal(shape)
    return tensor


def _get_endpoints(model_name, img_tensor):
    if model_name == "res50":
        with slim.arg_scope(resnet_v1.resnet_arg_scope()):
            _, end_points = resnet_v1.resnet_v1_50(img_tensor, 1000, is_training=False)
        return end_points["predictions"]

    elif model_name == "res152":
        with slim.arg_scope(resnet_v1.resnet_arg_scope()):
            _, end_points = resnet_v1.resnet_v1_152(img_tensor, 1000, is_training=False)
        return end_points["predictions"]

    elif model_name.startswith("mobilenet"):
        with tf.contrib.slim.arg_scope(mobilenet_v2.training_scope(is_training=False)):
            _, endpoints = mobilenet_v2.mobilenet(img_tensor)
        return endpoints["Predictions"]


def load_tf_sess(mem_frac=0.1, allow_growth=False, model_name=None, batch_size=1):
    graph = tf.Graph()
    with graph.as_default():
        shape = MODELS_TO_SHAPE[model_name]
        shape[0] = batch_size
        # img_tensor = tf.constant(
        #     np.random.randn(*shape).astype(np.float32)
        # )
        img_tensor = tf.placeholder(tf.float32, shape)
        predictions = _get_endpoints(model_name, img_tensor)
        saver = tf.train.Saver()
    config = tf.ConfigProto()
    config.gpu_options.allow_growth = True
    config.gpu_options.per_process_gpu_memory_fraction = 1.1
    config.gpu_options.allocator_type = "BFC"
    sess = tf.Session(config=config, graph=graph)
    saver.restore(sess, MODELS_TO_CKPT[model_name])
    return sess, img_tensor, predictions, graph


# How to merge many subgraphs into a single graph
# https://stackoverflow.com/questions/42858785/connect-input-and-output-tensors-of-two-different-graphs-tensorflow


def _create_subgraph(name_scope, ckpt_path, model_name):
    graph = tf.Graph()
    with graph.as_default():
        with tf.name_scope(name_scope):
            inp = tf.constant(
                np.random.randn(*MODELS_TO_SHAPE[model_name]).astype(np.float32)
            )
            predictions = _get_endpoints(model_name, inp)
            saver = tf.train.Saver()
            with tf.Session() as sess:
                saver.restore(sess, MODELS_TO_CKPT[model_name])
                saver.save(sess, ckpt_path)
    return graph.as_graph_def(), inp.name, predictions.name, saver


def load_tf_power_graph(mem_frac=0.1, allow_growth=False, model_name=None, num_graph=1):
    graph = tf.Graph()
    inps, outs, savers, ckpt_paths = [], [], [], []

    with graph.as_default():
        for i in range(num_graph):
            path = f"/tmp/graph_{i}.ckpt"
            graph_def, inp_name, out_name, saver = _create_subgraph(
                f"graph_{i}", path, model_name
            )

            inp, out = tf.import_graph_def(
                graph_def, return_elements=[inp_name, out_name], name=""
            )

            inps.append(inp)
            outs.append(out)
            savers.append(saver)
            ckpt_paths.append(path)

    config = tf.ConfigProto()
    config.gpu_options.allow_growth = allow_growth
    config.gpu_options.per_process_gpu_memory_fraction = mem_frac
    sess = tf.Session(config=config, graph=graph)

    for saver, path in zip(savers, ckpt_paths):
        saver.restore(sess, path)

    return sess, inps, outs
