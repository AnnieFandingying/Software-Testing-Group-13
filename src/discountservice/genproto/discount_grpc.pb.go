package genproto

import (
	context "context"

	grpc "google.golang.org/grpc"
	codes "google.golang.org/grpc/codes"
	status "google.golang.org/grpc/status"
)

const DiscountService_GetDiscount_FullMethodName = "/hipstershop.DiscountService/GetDiscount"

type DiscountServiceClient interface {
	GetDiscount(ctx context.Context, in *GetDiscountRequest, opts ...grpc.CallOption) (*GetDiscountResponse, error)
}

type discountServiceClient struct {
	cc grpc.ClientConnInterface
}

func NewDiscountServiceClient(cc grpc.ClientConnInterface) DiscountServiceClient {
	return &discountServiceClient{cc}
}

func (c *discountServiceClient) GetDiscount(ctx context.Context, in *GetDiscountRequest, opts ...grpc.CallOption) (*GetDiscountResponse, error) {
	out := new(GetDiscountResponse)
	err := c.cc.Invoke(ctx, DiscountService_GetDiscount_FullMethodName, in, out, opts...)
	if err != nil {
		return nil, err
	}
	return out, nil
}

type DiscountServiceServer interface {
	GetDiscount(context.Context, *GetDiscountRequest) (*GetDiscountResponse, error)
	mustEmbedUnimplementedDiscountServiceServer()
}

type UnimplementedDiscountServiceServer struct{}

func (UnimplementedDiscountServiceServer) GetDiscount(context.Context, *GetDiscountRequest) (*GetDiscountResponse, error) {
	return nil, status.Errorf(codes.Unimplemented, "method GetDiscount not implemented")
}
func (UnimplementedDiscountServiceServer) mustEmbedUnimplementedDiscountServiceServer() {}

type UnsafeDiscountServiceServer interface {
	mustEmbedUnimplementedDiscountServiceServer()
}

func RegisterDiscountServiceServer(s grpc.ServiceRegistrar, srv DiscountServiceServer) {
	s.RegisterService(&DiscountService_ServiceDesc, srv)
}

func _DiscountService_GetDiscount_Handler(srv interface{}, ctx context.Context, dec func(interface{}) error, interceptor grpc.UnaryServerInterceptor) (interface{}, error) {
	in := new(GetDiscountRequest)
	if err := dec(in); err != nil {
		return nil, err
	}
	if interceptor == nil {
		return srv.(DiscountServiceServer).GetDiscount(ctx, in)
	}
	info := &grpc.UnaryServerInfo{
		Server:     srv,
		FullMethod: DiscountService_GetDiscount_FullMethodName,
	}
	handler := func(ctx context.Context, req interface{}) (interface{}, error) {
		return srv.(DiscountServiceServer).GetDiscount(ctx, req.(*GetDiscountRequest))
	}
	return interceptor(ctx, in, info, handler)
}

var DiscountService_ServiceDesc = grpc.ServiceDesc{
	ServiceName: "hipstershop.DiscountService",
	HandlerType: (*DiscountServiceServer)(nil),
	Methods: []grpc.MethodDesc{
		{
			MethodName: "GetDiscount",
			Handler:    _DiscountService_GetDiscount_Handler,
		},
	},
	Streams:  []grpc.StreamDesc{},
	Metadata: "discount.proto",
}
