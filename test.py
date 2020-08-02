from backbones.insightface import *
from debug.createdata import pickle_load
from utilis.util import *
from utilis.attack import *
from backbones.unet import unet
from backbones.MobileFaceNet import mobilefacenet
import os
os.environ['CUDA_VISIBLE_DEVICES'] = '0'
epoch = 10
batch_size = 100


def mobile(inputs):
    prelogits, net_points = mobilefacenet(inputs, bottleneck_layer_size=192, reuse=tf.AUTO_REUSE)
    embeddings = tf.nn.l2_normalize(prelogits, 1, 1e-10, name='embeddings')
    return embeddings

EPOCH = 100
args = get_args()
config = yaml.load(open(args.config_path))
benchmark = tf.placeholder(dtype=tf.float32, shape=[None, 112, 112, 3], name='input_benchmark')
images = tf.placeholder(dtype=tf.float32, shape=[None, 112, 112, 3], name='input_image')
# train_placeholder = tf.placeholder(tf.bool)
# keep_props = tf.placeholder(tf.float32)
benchmark_embds = mobile(benchmark)
embds = mobile(images)

arc_embds, _ = get_embd(images, config)
arc_ben_embds, _ = get_embd(benchmark, config)

single_img = tf.placeholder(dtype=tf.float32, shape=[112, 112, 3], name='single_image')
jpeg_process = jpeg_pipe(single_img, quality=10)

def get_distance(embds1, embds2=benchmark_embds):
    embeddings1 = embds1 / tf.norm(embds1, axis=1, keepdims=True)
    embeddings2 = embds2 / tf.norm(embds2, axis=1, keepdims=True)
    diff = tf.subtract(embeddings1, embeddings2)
    distance = tf.reduce_sum(tf.multiply(diff, diff), axis=1)
    return distance

# adversarial
# grad_op = tf.gradients(dist, inputs)[0]
# x_fgsm = FGSM(inputs_placeholder, dist)

# x_ifgsm = IFGSM(inputs_placeholder, lambda f_embd: get_embd(f_embd),
#                                 lambda f_dis: get_distance(f_dis), 1)
# x_mifgsm = MI2FGSM(inputs_placeholder, lambda f_embd: get_embd(f_embd),
#                                 lambda f_dis: get_distance(f_dis), 1)
x_i2fgsm = I2FGSM(images, lambda f_embd: mobile(f_embd), lambda f_dis: get_distance(f_dis), 1)
# x_mi2fgsm = MI2FGSM(inputs_placeholder, lambda f_embd: get_embd(f_embd), lambda f_dis: get_distance(f_dis),1)

x_adv = x_i2fgsm
x_noise = x_adv - images


distances = get_distance(arc_embds, arc_ben_embds)
threshold = 1.02
distances = threshold - distances
prediction = tf.sign(distances)
correct_prediction = tf.count_nonzero(prediction+1, dtype=tf.float32)
accuracy = correct_prediction/batch_size


output = unet(x_noise)
loss_vars = tf.get_collection(tf.GraphKeys.GLOBAL_VARIABLES, scope='unet')

eps = 8 / 255. * 2
noise = tf.clip_by_value(output, - eps, eps)
image_adv = tf.clip_by_value(images + noise, -1.0, 1.0)

# accuracy = accurate(x, y)

variables_unet = tf.contrib.framework.get_variables_to_restore(include=['APF'])
saver_unet = tf.train.Saver(variables_unet)

config = tf.ConfigProto()
config.gpu_options.allow_growth = True
with tf.Session(config=config) as sess:

    sess.run(tf.global_variables_initializer())
    variables_mobilefacenet = tf.contrib.framework.get_variables_to_restore(include=['MobileFaceNet'])
    saver_m = tf.train.Saver(variables_mobilefacenet)
    variables_arc = tf.contrib.framework.get_variables_to_restore(include=['embd_extractor'])
    saver_a = tf.train.Saver(variables_arc)


    saver_m.restore(sess, '/data/jiaming/code/InsightFace-tensorflow/model/mobilefacenet/MobileFaceNet_TF.ckpt')  # the path you save the Mobilefacenet model.
    saver_unet.restore(sess, '/data/jiaming/code/InsightFace-tensorflow/model/mm/model_apf0.0016666666294137638.ckpt')

    saver_a.restore(sess, args.model_path)
    X = create_lfw_npy()
    print(X.shape)
    X_0 = X[0::2]
    X_1 = X[1::2]
    num_test = len(X_0)

    wo_acc = 0
    w_acc = 0
    test_loss = 0
    for j in range(num_test//batch_size):

        x = X_0[j*batch_size:(j+1)*batch_size]
        ben = X_1[j * batch_size:(j + 1) * batch_size]
        x_adv = sess.run(image_adv, feed_dict={images:x, benchmark:ben})
        x_adv_jpeg = np.zeros_like(x_adv)
        for i, data in enumerate(x_adv):
            x_adv_jpeg[i] = sess.run(jpeg_process, feed_dict={single_img:x_adv[i]})
        wo_acc += sess.run(accuracy, feed_dict={images: x_adv, benchmark: ben})
        w_acc += sess.run(accuracy,
                           feed_dict={images: x_adv_jpeg, benchmark: ben})
    print('w/o acc={:.4}, w acc={:.4}'.format(wo_acc/(num_test//batch_size), w_acc/(num_test//batch_size)))

