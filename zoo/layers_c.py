# Copyright 2019 Google LLC
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     https://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

import tensorflow as tf
from tensorflow.keras import Sequential, Model, Input
from tensorflow.keras import layers
from tensorflow.keras.layers import ReLU, Dense, Conv2D, Conv2DTranspose
from tensorflow.keras.layers import DepthwiseConv2D, SeparableConv2D, Dropout
from tensorflow.keras.layers import GlobalAveragePooling2D, Activation, BatchNormalization
from tensorflow.keras.regularizers import l2
from tensorflow.keras.optimizers import Adam, SGD
from tensorflow.compat.v1.keras.initializers import glorot_uniform, he_normal
from tensorflow.keras.callbacks import LearningRateScheduler
from tensorflow.keras.preprocessing.image import ImageDataGenerator
from tensorflow.keras.utils import to_categorical
import tensorflow_datasets as tfds
import tensorflow.keras.backend as K
import numpy as np
from sklearn.model_selection import train_test_split

import random
import math
import sys

class Layers(object):
    ''' Layers class for Composable Models '''

    init_weights = 'he_normal'  # weight initialization
    reg          = None         # kernel regularizer
    relu         = None         # ReLU max value
    bias         = True         # whether to use bias in dense/conv layers
 
    def __init__(self, init_weights, reg, relu, bias):
        """ Constructor
            init_weights : kernel initializer
            reg          : kernel regularizer
            relu         : clip value for ReLU
            bias         : whether to use bias
        """
        if init_weights is not None:
            self.init_weights = init_weights
        if reg is not None:
            self.reg = reg
        if relu is not None:
            self.relu = relu
        if bias is not None:
            self.bias = bias

    def prestem(self, inputs, **metaparameters):
      """ Construct a Pre-stem for Stem Group
          inputs : input to the pre-stem
          norm   : include normalization layer
      """
      x = inputs
      if 'norm' in metaparameters:
          norm = metaparameters['norm']
          if norm:
              x = self.Normalize(inputs)
      return x

    def stem(self, inputs, kernel_size=(7, 7), **metaparameters):
      """ Construct the Stem Group
          inputs     : input to the stem
          kernel_size: kernel (filter) size
          pooling    : pooling option
      """
      if 'pooling' in metaparameters:
          pooling = metaparameters['pooling']
      else:
          pooling = None

      x = self.Conv2D(inputs, kernel_size, strides=(1, 1), padding='same')
      x = self.BatchNormalization(x)
      x = self.ReLU(x)

      if pooling == 'max':
          x = MaxPooling2D((2, 2), strides=2)(x)
      elif pooling == 'feature':
          # feature pooling
          x = self.Conv2D(x, kernel_size, strides=(2, 2), padding='same')
          x = self.BatchNormalization(x)
          x = self.ReLU(x)
      return x

    def classifier(self, x, n_classes, **metaparameters):
      """ Construct the Classifier Group 
          x         : input to the classifier
          n_classes : number of output classes
          pooling   : type of feature map pooling
          dropout   : hidden dropout unit
      """
      if 'pooling' in metaparameters:
          pooling = metaparameters['pooling']
      else:
          pooling = GlobalAveragePooling2D
      if 'dropout' in metaparameters:
          dropout = metaparameters['dropout']
      else:
          dropout = None

      if pooling is not None:
          # Save the encoding layer (high dimensionality)
          self.encoding = x

          # Pooling at the end of all the convolutional groups
          x = pooling()(x)

          # Save the embedding layer (low dimensionality)
          self.embedding = x

      if dropout is not None:
          x = Dropout(dropout)(x)

      # Final Dense Outputting Layer for the outputs
      x = self.Dense(x, n_classes, use_bias=True, **metaparameters)
      
      # Save the pre-activation probabilities layer
      self.probabilities = x
      outputs = Activation('softmax')(x)
      # Save the post-activation probabilities layer
      self.softmax = outputs
      return outputs

    def top(self, layer):
        """ Add layer to the top of the neural network
            layer : layer to add
        """
        outputs = layer(self._model.outputs)
        self._model = Model(self._model.inputs, outputs)

    def summary(self):
        """ Call underlying summary method
        """
        self._model.summary()

    def Dense(self, x, units, activation=None, use_bias=True, **hyperparameters):
        """ Construct Dense Layer
            x           : input to layer
            activation  : activation function
            use_bias    : whether to use bias
            init_weights: kernel initializer
            reg         : kernel regularizer
        """
        if 'reg' in hyperparameters:
            reg = hyperparameters['reg']
        else:
            reg = self.reg
        if 'init_weights' in hyperparameters:
            init_weights = hyperparameters['init_weights']
        else:
            init_weights = self.init_weights
            
        x = Dense(units, activation, use_bias=use_bias,
                  kernel_initializer=init_weights, kernel_regularizer=reg)(x)
        return x

    def Conv2D(self, x, n_filters, kernel_size, strides=(1, 1), padding='valid', activation=None, **hyperparameters):
        """ Construct a Conv2D layer
            x           : input to layer
            n_filters   : number of filters
            kernel_size : kernel (filter) size
            strides     : strides
            padding     : how to pad when filter overlaps the edge
            activation  : activation function
            use_bias    : whether to include the bias
            init_weights: kernel initializer
            reg         : kernel regularizer
        """
        if 'reg' in hyperparameters:
            reg = hyperparameters['reg']
        else:
            reg = self.reg
        if 'init_weights' in hyperparameters:
            init_weights = hyperparameters['init_weights']
        else:
            init_weights = self.init_weights
        if 'bias' in hyperparameters:
            bias = hyperparameters['bias']
        else:
            bias = self.bias

        x = Conv2D(n_filters, kernel_size, strides=strides, padding=padding, activation=activation,
                   use_bias=bias, kernel_initializer=init_weights, kernel_regularizer=reg)(x)
        return x

    def Conv2DTranspose(self, x, n_filters, kernel_size, strides=(1, 1), padding='valid', activation=None, **hyperparameters):
        """ Construct a Conv2DTranspose layer
            x           : input to layer
            n_filters   : number of filters
            kernel_size : kernel (filter) size
            strides     : strides
            padding     : how to pad when filter overlaps the edge
            activation  : activation function
            use_bias    : whether to include the bias
            init_weights: kernel initializer
            reg         : kernel regularizer
        """
        if 'reg' in hyperparameters:
            reg = hyperparameters['reg']
        else:
            reg = self.reg
        if 'init_weights' in hyperparameters:
            init_weights = hyperparameters['init_weights']
        else:
            init_weights = self.init_weights 
        if 'bias' in hyperparameters:
            bias = hyperparameters['bias']
        else:
            bias = self.bias

        x = Conv2DTranspose(n_filters, kernel_size, strides=strides, padding=padding, activation=activation, 
			    use_bias=bias, kernel_initializer=init_weights, kernel_regularizer=reg)(x)
        return x

    def DepthwiseConv2D(self, x, kernel_size, strides=(1, 1), padding='valid', activation=None, **hyperparameters):
        """ Construct a DepthwiseConv2D layer
            x           : input to layer
            kernel_size : kernel (filter) size
            strides     : strides
            padding     : how to pad when filter overlaps the edge
            activation  : activation function
            use_bias    : whether to include the bias
            init_weights: kernel initializer
            reg         : kernel regularizer
        """
        if 'reg' in hyperparameters:
            reg = hyperparameters['reg']
        else:
            reg = self.reg
        if 'init_weights' in hyperparameters:
            init_weights = hyperparameters['init_weights']
        else:
            init_weights = self.init_weights
        if 'bias' in hyperparameters:
            bias = hyperparameters['bias']
        else:
            bias = self.bias

        x = DepthwiseConv2D(kernel_size, strides=strides, padding=padding, activation=activation, 
			    use_bias=bias, kernel_initializer=init_weights, kernel_regularizer=reg)(x)
        return x

    def SeparableConv2D(self, x, n_filters, kernel_size, strides=(1, 1), padding='valid', activation=None, **hyperparameters):
        """ Construct a SeparableConv2D layer
            x           : input to layer
            n_filters   : number of filters
            kernel_size : kernel (filter) size
            strides     : strides
            padding     : how to pad when filter overlaps the edge
            activation  : activation function
            use_bias    : whether to include the bias
            init_weights: kernel initializer
            reg         : kernel regularizer
        """
        if 'reg' in hyperparameters:
            reg = hyperparameters['reg']
        else:
            reg = self.reg
        if 'init_weights' in hyperparameters:
            init_weights = hyperparameters['init_weights']
        else:
            init_weights = self.init_weights
        if 'bias' in hyperparameters:
            bias = hyperparameters['bias']
        else:
            bias = self.bias

        x = SeparableConv2D(n_filters, kernel_size, strides=strides, padding=padding, activation=activation,
                            use_bias=bias, kernel_initializer=init_weights, kernel_regularizer=reg)(x)

        return x

    def ReLU(self, x):
        """ Construct ReLU activation function
            x  : input to activation function
        """
        x = ReLU(self.relu)(x)
        return x
	
    def HS(self, x):
        """ Construct Hard Swish activation function
            x  : input to activation function
        """
        return (x * K.relu(x + 3, max_value=6.0)) / 6.0

    def BatchNormalization(self, x, **params):
        """ Construct a Batch Normalization function
            x : input to function
        """
        x = BatchNormalization(epsilon=1.001e-5, **params)(x)
        return x

    ###
    # Pre-stem Layers
    ###

    class Normalize(layers.Layer):
        """ Custom Layer for Preprocessing Input - Normalization """
        def __init__(self, max=255.0, **parameters):
            """ Constructor """
            super(Composable.Normalize, self).__init__(**parameters)
            self.max = max
    
        def build(self, input_shape):
            """ Handler for Build (Functional) or Compile (Sequential) operation """
            self.kernel = None # no learnable parameters
    
        @tf.function
        def call(self, inputs):
            """ Handler for run-time invocation of layer """
            inputs = inputs / self.max
            return inputs

    class Standarize(layers.Layer):
        """ Custom Layer for Preprocessing Input - Standardization """
        def __init__(self, mean, std, **parameters):
            """ Constructor """
            super(Composable.Standardize, self).__init__(**parameters)
            self.mean = mean
            self.std  = std

        def build(self, input_shape):
            """ Handler for Build (Functional) or Compile (Sequential) operation """
            self.kernel = None # no learnable parameters

        @tf.function
        def call(self, inputs):
            """ Handler for run-time invocation of layer """
            inputs = (inputs - self.mean) / self.std
            return inputs

 

