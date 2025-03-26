<!-- <p align="center">
<img src="/src/frontend/static/icons/Hipster_HeroLogoMaroon.svg" width="300" alt="Online Boutique" />
</p> -->
![Continuous Integration](https://github.com/GoogleCloudPlatform/microservices-demo/workflows/Continuous%20Integration%20-%20Main/Release/badge.svg)

Online Boutique是一款云优先的微服务演示应用程序。该应用程序是一款基于 Web 的电子商务应用程序，用户可以在其中浏览商品、将其添加到购物车并购买。

Google 使用此应用程序来演示开发人员如何使用 Google Cloud 产品对企业应用程序进行现代化改造，这些产品包括：Google Kubernetes Engine (GKE)、Cloud Service Mesh (CSM)、gRPC、Cloud Operations、Spanner、Memorystore、AlloyDB和Gemini。此应用程序适用于任何 Kubernetes 集群。

## 架构

**Online Boutique** 由 11 个用不同语言编写的微服务组成，这些微服务通过 gRPC 相互通信。.

[![Architecture of
microservices](/docs/img/architecture-diagram.png)](/docs/img/architecture-diagram.png)

| 服务                                                  | 语言            | 描述                                            |
|-----------------------------------------------------|---------------|-----------------------------------------------|
| [frontend](/src/frontend)                           | Go            | 用户无需注册/登录，并自动为所有用户生成会话 ID免登录.                 |
| [cartservice](/src/cartservice)                     | C#            | 用户购物车中的商品存储在Redis中并检索.                        |
| [productcatalogservice](/src/productcatalogservice) | Go            | 提供来自 JSON 文件的产品列表以及搜索产品和获取单个产品的能力.            |
| [currencyservice](/src/currencyservice)             | Node.js       | 将一种货币金额转换为另一种货币。使用从欧洲中央银行获取的实际值。这是 QPS 最高的服务. |
| [paymentservice](/src/paymentservice)               | Node.js       | 使用给定的信用卡信息（模拟）收取给定的金额并返回交易 ID.                |
| [shippingservice](/src/shippingservice)             | Go            | 根据购物车提供运费估算。将物品运送到指定地址（模拟）                    |
| [emailservice](/src/emailservice)                   | Python        | 向用户发送订单确认电子邮件（模拟）                             |
| [checkoutservice](/src/checkoutservice)             | Go            | 检索用户购物车，准备订单并安排付款、运输和电子邮件通知。                  |
| [recommendationservice](/src/recommendationservice) | Python        | 根据购物车中的内容推荐其他产品。                              |
| [adservice](/src/adservice)                         | Java          | 根据给定的上下文词提供文字广告。                              |
| [loadgenerator](/src/loadgenerator)                 | Python/Locust | 持续向前端发送模拟真实用户购物流程的请求。                         |

## 截图

| 首页                                                                                                                    | 结算页                                                                                                                   |
|-----------------------------------------------------------------------------------------------------------------------|-----------------------------------------------------------------------------------------------------------------------|
| [![Screenshot of store homepage](/docs/img/online-boutique-frontend-1.png)](/docs/img/online-boutique-frontend-1.png) | [![Screenshot of checkout screen](/docs/img/online-boutique-frontend-2.png)](/docs/img/online-boutique-frontend-2.png) |

## 快速开始 (GKE)

1. 具备以下要求:
   - [Google Cloud project](https://cloud.google.com/resource-manager/docs/creating-managing-projects#creating_a_project).
   - Shell 环境有 `gcloud`, `git`, 和 `kubectl`.

2. 克隆最新的主要版本.

   ```sh
   git clone --depth 1 --branch v0 https://github.com/GoogleCloudPlatform/microservices-demo.git
   cd microservices-demo/
   ```

3. 启用 Google Kubernetes 引擎 API

   ```sh
   export PROJECT_ID=<PROJECT_ID>
   export REGION=us-central1
   gcloud services enable container.googleapis.com \
     --project=${PROJECT_ID}
   ```

4. 创建 GKE 集群并获取其证书

   ```sh
   gcloud container clusters create-auto online-boutique \
     --project=${PROJECT_ID} --region=${REGION}
   ```

5. 部署到群集.

   ```sh
   kubectl apply -f ./release/kubernetes-manifests.yaml
   ```

6. 等待容器运行时准备就绪.

   ```sh
   kubectl get pods
   ```

   ```
   NAME                                     READY   STATUS    RESTARTS   AGE
   adservice-76bdd69666-ckc5j               1/1     Running   0          2m58s
   cartservice-66d497c6b7-dp5jr             1/1     Running   0          2m59s
   checkoutservice-666c784bd6-4jd22         1/1     Running   0          3m1s
   currencyservice-5d5d496984-4jmd7         1/1     Running   0          2m59s
   emailservice-667457d9d6-75jcq            1/1     Running   0          3m2s
   frontend-6b8d69b9fb-wjqdg                1/1     Running   0          3m1s
   loadgenerator-665b5cd444-gwqdq           1/1     Running   0          3m
   paymentservice-68596d6dd6-bf6bv          1/1     Running   0          3m
   productcatalogservice-557d474574-888kr   1/1     Running   0          3m
   recommendationservice-69c56b74d4-7z8r5   1/1     Running   0          3m1s
   redis-cart-5f59546cdd-5jnqf              1/1     Running   0          2m58s
   shippingservice-6ccc89f8fd-v686r         1/1     Running   0          2m58s
   ```

7. 使用前端的外部 IP 在浏览器中访问 Web 前端。

   ```sh
   kubectl get service frontend-external | awk '{print $4}'
   ```

   通过网络浏览器访问http://EXTERNAL_IP您的在线精品店实例。
